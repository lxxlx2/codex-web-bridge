#!/usr/bin/env python3
"""One-shot standalone S3 CLI/live acceptance for Codex Web Bridge.

The runner verifies the standalone checkout itself. It keeps raw Codex JSONL and
all thread identifiers under ``~/.uwa`` with private permissions, prints only
sanitized gate results, never switches to the official provider, and never
commits or pushes the repository.

Coverage:
- clean/current standalone-dev checkout and local non-live safety regressions;
- exact UWA/chatgpt/high configuration and owned standalone listener;
- real Codex CLI client-tool round trip across a UWA process restart;
- same-thread continuation after restart;
- native auto-compaction trigger plus remote V2 compaction evidence;
- post-compaction same-thread recovery through a real local exec_command;
- metadata-only route evidence and request-manager cleanup.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import codex_auto_compact_trigger_probe as trigger_probe
import codex_desktop_acceptance as desktop
import codex_large_context_acceptance as large_context
import codex_provider_switch as provider_switch
import codex_remote_compaction_compat as remote_compat
import codex_remote_compaction_trigger_probe as remote_trigger
import codex_route_audit as route_audit
import codex_uwa_lifecycle as lifecycle


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "standalone-dev"
EXPECTED_PROVIDER = "uwa"
EXPECTED_MODEL = "chatgpt"
EXPECTED_EFFORT = "high"
DEFAULT_ACCEPTANCE_ROOT = Path.home() / "uwa-codex-acceptance"
DEFAULT_PRIVATE_ROOT = Path.home() / ".uwa" / "standalone-s3"
DEFAULT_TURN_TIMEOUT_SEC = 600
DEFAULT_COMPACTION_TIMEOUT_SEC = 900
DEFAULT_CLEANUP_TIMEOUT_SEC = 30.0
KNOWN_INTEGRATED_REPO = "lxxlx2/universal-web-api"


class GateFailure(RuntimeError):
    def __init__(self, gate: str, detail: str = "") -> None:
        super().__init__(detail or gate)
        self.gate = gate
        self.detail = detail


@dataclass
class CodexObservation:
    returncode: int
    thread_ids: list[str] = field(default_factory=list)
    agent_messages: list[str] = field(default_factory=list)
    command_count: int = 0
    file_change_count: int = 0
    mcp_call_count: int = 0
    turn_completed_count: int = 0

    @property
    def final_message(self) -> str:
        return self.agent_messages[-1].strip() if self.agent_messages else ""

    @property
    def tool_effect_count(self) -> int:
        return self.command_count + self.file_change_count + self.mcp_call_count


def _run(
    args: Sequence[str],
    *,
    cwd: Path = REPO_ROOT,
    input_text: str | None = None,
    timeout_sec: int = 120,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(args),
            cwd=str(cwd),
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GateFailure("subprocess_timeout", f"timeout={timeout_sec}s") from exc


def _git(*args: str, timeout_sec: int = 60) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd=REPO_ROOT, timeout_sec=timeout_sec)


def _private_dir(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = root.expanduser() / stamp
    suffix = 0
    candidate = path
    while candidate.exists():
        suffix += 1
        candidate = Path(f"{path}-{suffix}")
    candidate.mkdir(parents=True, mode=0o700)
    try:
        candidate.chmod(0o700)
    except OSError:
        pass
    return candidate


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    path.write_text(text, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _parse_codex_jsonl(text: str, returncode: int) -> CodexObservation:
    obs = CodexObservation(returncode=returncode)
    for raw in text.splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "")
        if event_type == "thread.started":
            value = event.get("thread_id")
            if isinstance(value, str) and value:
                obs.thread_ids.append(value)
            continue
        if event_type == "turn.completed":
            obs.turn_completed_count += 1
            continue
        if event_type != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "")
        if item_type == "agent_message":
            value = item.get("text")
            if isinstance(value, str):
                obs.agent_messages.append(value)
        elif item_type == "command_execution":
            obs.command_count += 1
        elif item_type == "file_change":
            obs.file_change_count += 1
        elif item_type == "mcp_tool_call":
            obs.mcp_call_count += 1
    return obs


def _run_codex_turn(
    *,
    codex: str,
    cwd: Path,
    prompt: str,
    trace_path: Path,
    thread_id: str | None,
    timeout_sec: int,
) -> CodexObservation:
    args = [codex, "exec", "--json", "--color", "never"]
    if thread_id is None:
        args.append("-")
    else:
        args.extend(["resume", thread_id, "-"])
    result = _run(args, cwd=cwd, input_text=prompt, timeout_sec=timeout_sec)
    _write_private(trace_path, result.stdout)
    return _parse_codex_jsonl(result.stdout, result.returncode)


def _unique_thread_id(obs: CodexObservation) -> str:
    values = list(dict.fromkeys(obs.thread_ids))
    if len(values) != 1:
        raise GateFailure("thread_capture", f"thread_count={len(values)}")
    return values[0]


def _resume_thread_matches(obs: CodexObservation, expected: str) -> bool:
    return all(value == expected for value in obs.thread_ids)


def _preflight_repo() -> None:
    if platform.system() != "Darwin":
        raise GateFailure("platform", "macOS_required_for_current_live_gate")

    branch = _git("branch", "--show-current")
    if branch.returncode != 0 or branch.stdout.strip() != EXPECTED_BRANCH:
        raise GateFailure("branch", f"expected={EXPECTED_BRANCH}")

    status = _git("status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0:
        raise GateFailure("git_status")
    if status.stdout.strip():
        raise GateFailure("dirty_worktree", "tracked_or_untracked_changes_present")

    fetch = _git("fetch", "-q", "origin", EXPECTED_BRANCH, timeout_sec=120)
    if fetch.returncode != 0:
        raise GateFailure("git_fetch", "unable_to_refresh_origin")
    head = _git("rev-parse", "HEAD")
    remote = _git("rev-parse", f"origin/{EXPECTED_BRANCH}")
    if head.returncode or remote.returncode or head.stdout.strip() != remote.stdout.strip():
        raise GateFailure("stale_checkout", "local_head_does_not_match_origin")

    if shutil.which("codex") is None:
        raise GateFailure("codex_cli", "codex_not_found")


def _normalize_remote(url: str) -> str:
    value = str(url or "").strip()
    if value.startswith("git@github.com:"):
        value = "https://github.com/" + value[len("git@github.com:") :]
    value = value.removesuffix(".git").rstrip("/")
    return value.lower()


def _is_known_integrated_checkout(path: Path) -> bool:
    result = _run(
        ["git", "-C", str(path), "remote", "get-url", "origin"],
        cwd=REPO_ROOT,
        timeout_sec=30,
    )
    if result.returncode != 0:
        return False
    return _normalize_remote(result.stdout) == f"https://github.com/{KNOWN_INTEGRATED_REPO}".lower()


def _start_standalone_listener() -> str:
    pids = lifecycle.listener_pids()
    expected = REPO_ROOT.resolve()
    if not pids:
        lifecycle.start_uwa(repo_root=REPO_ROOT)
        return "STARTED"

    owners: set[Path] = set()
    for pid in pids:
        cwd = lifecycle.process_cwd(pid)
        if cwd is None:
            raise GateFailure("listener_owner", "listener_cwd_unknown")
        owners.add(cwd.expanduser().resolve())

    if owners == {expected}:
        lifecycle.restart_uwa(repo_root=REPO_ROOT)
        return "RESTARTED"

    if len(owners) == 1:
        owner = next(iter(owners))
        old_tool = owner / "tools" / "codex_uwa_lifecycle.py"
        if old_tool.is_file() and _is_known_integrated_checkout(owner):
            stopped = _run(
                [sys.executable, str(old_tool), "stop", "--root", str(owner)],
                cwd=owner,
                timeout_sec=45,
            )
            if stopped.returncode != 0 or lifecycle.listener_pids():
                raise GateFailure("integrated_listener_transition", "old_listener_stop_failed")
            lifecycle.start_uwa(repo_root=REPO_ROOT)
            return "MIGRATED_FROM_INTEGRATED"

    raise GateFailure("foreign_listener", "tcp_8199_owned_by_unrecognized_checkout")


def _restart_standalone_listener() -> None:
    try:
        lifecycle.restart_uwa(repo_root=REPO_ROOT)
    except Exception as exc:
        raise GateFailure("uwa_restart", exc.__class__.__name__) from exc


def _health_payload(timeout: float = 5.0) -> dict[str, Any]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8199/health", timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise GateFailure("health", "health_unavailable") from exc
    if not isinstance(data, dict):
        raise GateFailure("health", "invalid_health_payload")
    return data


def _health_ready(*, require_clean: bool) -> dict[str, Any]:
    data = _health_payload()
    browser = data.get("browser") if isinstance(data.get("browser"), dict) else {}
    if data.get("service") != "healthy" or browser.get("connected") is not True:
        raise GateFailure("health", "browser_not_connected")
    try:
        running = int(data.get("running_count", 0) or 0)
    except (TypeError, ValueError) as exc:
        raise GateFailure("health", "invalid_running_count") from exc
    if require_clean and running != 0:
        raise GateFailure("request_cleanup", f"running_count={running}")
    return data


def _wait_request_cleanup(timeout_sec: float = DEFAULT_CLEANUP_TIMEOUT_SEC) -> None:
    deadline = time.monotonic() + timeout_sec
    latest = -1
    while time.monotonic() < deadline:
        try:
            data = _health_payload(timeout=2.0)
            latest = int(data.get("running_count", 0) or 0)
        except GateFailure:
            latest = -1
        if latest == 0:
            _health_ready(require_clean=True)
            return
        time.sleep(0.5)
    raise GateFailure("request_cleanup", f"running_count={latest}")


def _configure_uwa_route() -> None:
    config_path = provider_switch.default_config_path().expanduser()
    state_path = provider_switch.default_state_path().expanduser()
    legacy = provider_switch.default_legacy_official_path().expanduser()
    try:
        provider_switch.write_uwa(
            config_path,
            state_path=state_path,
            legacy_official_path=legacy,
        )
        remote_compat.enable_file(config_path)
    except Exception as exc:
        raise GateFailure("uwa_config", exc.__class__.__name__) from exc

    route = route_audit.read_config_route(config_path)
    if (
        route.provider != EXPECTED_PROVIDER
        or route.model != EXPECTED_MODEL
        or route.effort != EXPECTED_EFFORT
    ):
        raise GateFailure("uwa_config", "route_metadata_mismatch")


def _validation_python() -> str:
    if os.name == "nt":
        path = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        path = REPO_ROOT / ".venv" / "bin" / "python"
    if not path.is_file():
        raise GateFailure("validation_python", "standalone_venv_missing_after_start")
    return str(path)


def _run_local_gates(python: str, private_dir: Path) -> None:
    commands: list[tuple[str, list[str], int]] = [
        (
            "public_repo_safety",
            [python, str(REPO_ROOT / "tools" / "public_repo_safety_check.py")],
            120,
        ),
        (
            "dependency_audit",
            [python, str(REPO_ROOT / "tools" / "standalone_dependency_audit.py"), "--check"],
            180,
        ),
        (
            "focused_unittest",
            [
                python,
                "-m",
                "unittest",
                "-q",
                "tests.test_codex_v2_stream_cancellation",
                "tests.test_codex_runtime_extraction",
                "tests.test_codex_chatgpt_executor",
                "tests.test_standalone_api_import_boundary",
                "tests.test_standalone_entrypoint",
            ],
            240,
        ),
    ]
    for name, args, timeout_sec in commands:
        result = _run(args, cwd=REPO_ROOT, timeout_sec=timeout_sec)
        _write_private(private_dir / f"local-{name}.log", result.stdout)
        if result.returncode != 0:
            raise GateFailure(name, f"rc={result.returncode}")

    status = _git("status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0 or status.stdout.strip():
        raise GateFailure("runtime_repo_cleanliness", "live_setup_changed_repository")


def _prepare_context_workspace(root: Path) -> Path:
    with contextlib.redirect_stdout(io.StringIO()):
        desktop.prepare(root, "context")
        rc = desktop.preflight(root, "context")
    if rc != 0:
        raise GateFailure("context_workspace", "preflight_failed")
    return root.expanduser().resolve()


def _restart_context_prompt() -> str:
    marker = desktop.MARKER
    return (
        "这是同一个 Codex 对话的第二轮重启恢复验收。不要向我询问上一轮令牌，也不要从 "
        "~/.codex、~/.uwa、日志、SQLite、PROMPTS.md 或其他会话文件中搜索令牌。"
        f"第一步必须通过客户端 exec_command 在当前工作区执行 pwd && test -f {marker} && test -d context。"
        "如果工作区校验失败，只回复 ACCEPTANCE_WORKSPACE_MISMATCH。"
        "校验成功后，只使用上一轮对话上下文中记住的令牌，并且必须通过客户端 exec_command "
        "创建 context/result.txt，使文件精确包含该令牌和一个换行；随后再次通过客户端 exec_command "
        "读取并确认该文件。不要调用网页侧工具代替本地工具。完成后只回复 CONTEXT_PASS。"
    )


def _run_restart_continuity(
    *,
    codex: str,
    root: Path,
    private_dir: Path,
    timeout_sec: int,
) -> None:
    seed = _run_codex_turn(
        codex=codex,
        cwd=root,
        prompt=desktop.PROMPTS["context_1"],
        trace_path=private_dir / "restart-seed.jsonl",
        thread_id=None,
        timeout_sec=timeout_sec,
    )
    if seed.returncode != 0 or seed.final_message != "CONTEXT_READY" or seed.tool_effect_count != 0:
        raise GateFailure("restart_seed", "seed_contract_failed")
    thread_id = _unique_thread_id(seed)

    _wait_request_cleanup()
    _restart_standalone_listener()
    _health_ready(require_clean=True)

    resumed = _run_codex_turn(
        codex=codex,
        cwd=root,
        prompt=_restart_context_prompt(),
        trace_path=private_dir / "restart-resume.jsonl",
        thread_id=thread_id,
        timeout_sec=timeout_sec,
    )
    if resumed.returncode != 0:
        raise GateFailure("restart_resume", f"rc={resumed.returncode}")
    if not _resume_thread_matches(resumed, thread_id):
        raise GateFailure("restart_resume", "thread_identity_mismatch")
    if resumed.final_message != "CONTEXT_PASS":
        raise GateFailure("restart_resume", "final_reply_mismatch")
    if resumed.command_count < 1:
        raise GateFailure("restart_resume", "real_exec_command_not_observed")
    result_path = root / "context" / "result.txt"
    try:
        actual = result_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GateFailure("restart_resume", "result_file_missing") from exc
    if actual != desktop.CONTEXT_TOKEN + "\n":
        raise GateFailure("restart_resume", "context_token_mismatch")
    _wait_request_cleanup()


def _parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and " " not in key:
            values[key] = value.strip()
    return values


def _probe_trigger_reply_acceptable(
    values: dict[str, str],
) -> bool:
    return (
        values.get("TRIGGER_REPLY_EXACT") == "YES"
        or values.get(
            "TRIGGER_REPLY_DEFERRED_TO_POST_COMPACTION_RECOVERY"
        ) == "YES"
    )


def _run_remote_compaction_recovery(
    *,
    codex: str,
    root: Path,
    private_dir: Path,
    timeout_sec: int,
) -> None:
    remote_trigger.configure_remote_v2_markers()
    captured_thread: dict[str, str] = {}
    original_turn = trigger_probe._run_turn_preserving_failure

    def capture_turn(**kwargs: Any):
        obs = original_turn(**kwargs)
        ids = list(dict.fromkeys(obs.thread_ids))
        if ids and "id" not in captured_thread:
            if len(ids) != 1:
                raise RuntimeError("ambiguous private thread identity")
            captured_thread["id"] = ids[0]
        if "id" in captured_thread and any(value != captured_thread["id"] for value in ids):
            raise RuntimeError("private thread identity changed during compaction probe")
        return obs

    trigger_probe._run_turn_preserving_failure = capture_turn
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            rc = trigger_probe.run(
                root,
                codex=codex,
                uwa_log=large_context.DEFAULT_UWA_LOG.expanduser(),
                coarse_bytes=trigger_probe.DEFAULT_COARSE_BYTES,
                fine_bytes=trigger_probe.DEFAULT_FINE_BYTES,
                coarse_guard_tokens=trigger_probe.DEFAULT_COARSE_GUARD_TOKENS,
                max_coarse_rounds=trigger_probe.DEFAULT_MAX_COARSE_ROUNDS,
                max_fine_rounds=trigger_probe.DEFAULT_MAX_FINE_ROUNDS,
                timeout_sec=timeout_sec,
            )
    except Exception as exc:
        _write_private(private_dir / "remote-compaction-probe.log", buffer.getvalue())
        raise GateFailure("remote_compaction_probe", exc.__class__.__name__) from exc
    finally:
        trigger_probe._run_turn_preserving_failure = original_turn

    probe_output = buffer.getvalue()
    _write_private(private_dir / "remote-compaction-probe.log", probe_output)
    values = _parse_key_values(probe_output)
    if rc != 0:
        raise GateFailure("remote_compaction_probe", f"rc={rc}")
    if "AUTO_COMPACT_TRIGGER_PROBE_PASS" not in probe_output:
        raise GateFailure("native_auto_compaction", "trigger_marker_missing")

    if not _probe_trigger_reply_acceptable(values):
        raise GateFailure(
            "native_auto_compaction",
            "trigger_reply_contract_unproven",
        )

    try:
        rollout_delta = int(values.get("ROLLOUT_COMPACT_MARKER_DELTA", "0") or 0)
        remote_route_delta = int(values.get("REMOTE_COMPACT_ROUTE_DELTA", "0") or 0)
        remote_success_delta = int(values.get("REMOTE_COMPACT_SUCCESS_DELTA", "0") or 0)
    except ValueError as exc:
        raise GateFailure("remote_compaction_probe", "invalid_probe_counters") from exc
    if rollout_delta < 1:
        raise GateFailure("native_auto_compaction", "rollout_compact_event_missing")
    if (
        values.get("AUTO_COMPACT_MODE") != "REMOTE"
        or remote_route_delta < 1
        or remote_success_delta < 1
    ):
        raise GateFailure("remote_v2_compaction", "remote_completion_not_proven")

    thread_id = captured_thread.get("id", "")
    if not thread_id:
        raise GateFailure("remote_compaction_probe", "private_thread_not_captured")

    try:
        recovery = large_context._run_codex_turn(
            codex=codex,
            root=root,
            prompt=large_context.build_final_prompt(),
            trace_path=private_dir / "post-compaction-recovery.jsonl",
            thread_id=thread_id,
            timeout_sec=timeout_sec,
        )
    except RuntimeError as exc:
        raise GateFailure(
            "post_compaction_recovery",
            "codex_turn_runtime_error",
        ) from exc
    if recovery.returncode != 0:
        raise GateFailure("post_compaction_recovery", f"rc={recovery.returncode}")
    if not large_context._verify_thread(recovery, thread_id):
        raise GateFailure(
            "post_compaction_recovery",
            "thread_identity_mismatch",
        )
    if not large_context._workspace_validation_observed(
        recovery.commands
    ):
        raise GateFailure(
            "post_compaction_recovery",
            "workspace_validation_command_missing",
        )
    if recovery.final_message != "LARGE_CONTEXT_PASS":
        raise GateFailure(
            "post_compaction_recovery",
            "final_reply_mismatch",
        )
    if recovery.tool_effect_count < 1 or not recovery.commands:
        raise GateFailure("post_compaction_recovery", "real_client_tool_missing")
    if not large_context._final_commands_safe(recovery.commands):
        raise GateFailure("post_compaction_recovery", "unsafe_private_history_search_detected")
    result_path = root / large_context.RESULT_RELATIVE
    try:
        actual = result_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GateFailure("post_compaction_recovery", "result_file_missing") from exc
    if actual != large_context.TOKEN + "\n":
        raise GateFailure("post_compaction_recovery", "token_mismatch")
    _wait_request_cleanup()


def _route_gate(marker_epoch: float) -> None:
    config = route_audit.read_config_route()
    session = route_audit.latest_session_route(since_epoch=marker_epoch, max_age_hours=24.0)
    wire = route_audit.scan_wire_activity(since_epoch=marker_epoch)
    ok, failures = route_audit.expectation_result(
        session,
        wire,
        expect_provider=EXPECTED_PROVIDER,
        expect_model=EXPECTED_MODEL,
        expect_effort=EXPECTED_EFFORT,
    )
    if ok is not True:
        raise GateFailure("route_audit", ",".join(failures) or "expectation_failed")
    if config.provider != EXPECTED_PROVIDER or config.model != EXPECTED_MODEL or config.effort != EXPECTED_EFFORT:
        raise GateFailure("route_audit", "configured_route_mismatch")
    if wire.response_count < 1:
        raise GateFailure("route_audit", "wire_response_missing")
    if wire.latest_model != EXPECTED_MODEL or wire.latest_effort != EXPECTED_EFFORT:
        raise GateFailure("route_audit", "wire_model_or_effort_mismatch")
    if wire.latest_status not in {"completed", "incomplete"}:
        raise GateFailure("route_audit", "wire_terminal_status_unproven")


def _print_pass_summary(listener_transition: str) -> None:
    print("S3_REPO_PREFLIGHT=PASS")
    print(f"S3_LISTENER_TRANSITION={listener_transition}")
    print("S3_LOCAL_SAFETY_REGRESSION=PASS")
    print("S3_UWA_HEALTH=PASS")
    print("S3_REAL_CLIENT_TOOL=PASS")
    print("S3_SAME_THREAD_RESTART_RECOVERY=PASS")
    print("S3_NATIVE_AUTO_COMPACTION=PASS")
    print("S3_REMOTE_V2_COMPACTION=PASS")
    print("S3_POST_COMPACTION_RECOVERY=PASS")
    print("S3_ROUTE_UWA_CHATGPT_HIGH=PASS")
    print("S3_REQUEST_MANAGER_CLEAN=PASS")
    print("S3_REPOSITORY_CLEAN_AFTER_LIVE=PASS")
    print("STANDALONE_S3=PASS_LIVE_CLOSED")


def run(
    *,
    acceptance_root: Path,
    private_root: Path,
    turn_timeout_sec: int,
    compaction_timeout_sec: int,
) -> int:
    private_dir = _private_dir(private_root)
    listener_transition = "UNKNOWN"
    try:
        _preflight_repo()
        print("S3_PHASE=REPO_PREFLIGHT_PASS")

        _configure_uwa_route()
        print("S3_PHASE=UWA_ROUTE_CONFIGURED")

        listener_transition = _start_standalone_listener()
        _health_ready(require_clean=True)
        print("S3_PHASE=STANDALONE_LISTENER_READY")

        python = _validation_python()
        _run_local_gates(python, private_dir)
        print("S3_PHASE=LOCAL_GATES_PASS")

        marker_epoch = route_audit.write_marker()
        root = _prepare_context_workspace(acceptance_root)
        codex = shutil.which("codex") or "codex"

        _run_restart_continuity(
            codex=codex,
            root=root,
            private_dir=private_dir,
            timeout_sec=turn_timeout_sec,
        )
        print("S3_PHASE=RESTART_CONTINUITY_PASS")

        _run_remote_compaction_recovery(
            codex=codex,
            root=root,
            private_dir=private_dir,
            timeout_sec=compaction_timeout_sec,
        )
        print("S3_PHASE=COMPACTION_RECOVERY_PASS")

        _wait_request_cleanup()
        _health_ready(require_clean=True)
        _route_gate(marker_epoch)

        status = _git("status", "--porcelain=v1", "--untracked-files=all")
        if status.returncode != 0 or status.stdout.strip():
            raise GateFailure("final_repo_cleanliness", "repository_changed_during_live_gate")

        _write_private(
            private_dir / "result.txt",
            "STANDALONE_S3=PASS_LIVE_CLOSED\n"
            "provider=uwa\nmodel=chatgpt\neffort=high\n",
        )
        _print_pass_summary(listener_transition)
        return 0
    except GateFailure as exc:
        _write_private(
            private_dir / "result.txt",
            f"STANDALONE_S3=FAIL\nFAILURE_CLASS={exc.gate}\nDETAIL={exc.detail}\n",
        )
        print("STANDALONE_S3=FAIL")
        print(f"FAILURE_CLASS={exc.gate}")
        if exc.detail:
            print(f"FAILURE_DETAIL={exc.detail}")
        print("PRIVATE_EVIDENCE_RECORDED=YES")
        return 1
    except Exception as exc:
        _write_private(
            private_dir / "result.txt",
            f"STANDALONE_S3=FAIL\nFAILURE_CLASS=unexpected_exception\nDETAIL={exc.__class__.__name__}\n",
        )
        print("STANDALONE_S3=FAIL")
        print("FAILURE_CLASS=unexpected_exception")
        print(f"FAILURE_DETAIL={exc.__class__.__name__}")
        print("PRIVATE_EVIDENCE_RECORDED=YES")
        return 1


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acceptance-root", type=Path, default=DEFAULT_ACCEPTANCE_ROOT)
    parser.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE_ROOT)
    parser.add_argument("--turn-timeout-sec", type=int, default=DEFAULT_TURN_TIMEOUT_SEC)
    parser.add_argument("--compaction-timeout-sec", type=int, default=DEFAULT_COMPACTION_TIMEOUT_SEC)
    args = parser.parse_args()

    if args.turn_timeout_sec < 60 or args.compaction_timeout_sec < 60:
        raise SystemExit("timeouts must be at least 60 seconds")

    return run(
        acceptance_root=args.acceptance_root,
        private_root=args.private_root,
        turn_timeout_sec=args.turn_timeout_sec,
        compaction_timeout_sec=args.compaction_timeout_sec,
    )


if __name__ == "__main__":
    raise SystemExit(main())
