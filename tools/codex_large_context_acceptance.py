#!/usr/bin/env python3
"""Automated P1.2 native Codex large-context / compaction acceptance.

This runner keeps the synthetic memory token conversation-only, grows one Codex
thread with deterministic filler through ``codex exec resume``, watches the
private UWA log only for bounded compaction lifecycle markers, and finally asks
Codex to recover the original token through a real local tool write.

Private Codex JSONL output is written under ``~/.uwa/p1-large-context`` and is
never copied into the public repository. The acceptance workspace receives only
synthetic result/evidence files after the final turn.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = Path.home() / "uwa-codex-acceptance"
DEFAULT_UWA_LOG = Path.home() / ".uwa" / "uwa.log"
DEFAULT_PRIVATE_TRACE_ROOT = Path.home() / ".uwa" / "p1-large-context"
MARKER = ".uwa_codex_acceptance"
SCENARIO = "large_context"
TOKEN = "ORBIT-5921"
RESULT_RELATIVE = Path(SCENARIO) / "result.txt"
EVIDENCE_RELATIVE = Path(SCENARIO) / "evidence.json"
COMPACT_ROUTE_MARKER = "/v1/responses/compact"
COMPACT_SUCCESS_MARKER = "[CODEX_COMPACT] compacted history into"
DEFAULT_FILLER_BYTES = 20_000
DEFAULT_MAX_ROUNDS = 24
DEFAULT_POST_COMPACT_ROUNDS = 1
DEFAULT_TIMEOUT_SEC = 900


@dataclass
class ExecObservation:
    returncode: int
    thread_ids: list[str] = field(default_factory=list)
    agent_messages: list[str] = field(default_factory=list)
    input_tokens: list[int] = field(default_factory=list)
    output_tokens: list[int] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    file_change_count: int = 0
    mcp_call_count: int = 0
    raw: str = ""

    @property
    def final_message(self) -> str:
        return self.agent_messages[-1].strip() if self.agent_messages else ""

    @property
    def tool_effect_count(self) -> int:
        return len(self.commands) + self.file_change_count + self.mcp_call_count


@dataclass
class LogEvidence:
    next_offset: int
    route_markers: int
    success_markers: int
    log_reset: bool


def _chmod_private(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        pass


def _guard_root(root: Path) -> Path:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"Acceptance workspace does not exist: {root}")
    if not (root / MARKER).is_file():
        raise SystemExit(f"Refusing unmarked acceptance workspace: {root}")
    if not (root / ".git").is_dir():
        raise SystemExit(f"Acceptance workspace is missing Git baseline: {root}")
    return root


def _ensure_base_workspace(root: Path) -> Path:
    root = root.expanduser().resolve()
    if root.exists():
        return _guard_root(root)

    harness = REPO_ROOT / "tools" / "codex_desktop_acceptance.py"
    result = subprocess.run(
        [sys.executable, str(harness), "setup", "--root", str(root)],
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        raise SystemExit("Unable to create base acceptance workspace:\n" + result.stdout)
    return _guard_root(root)


def prepare(root: Path) -> Path:
    root = _ensure_base_workspace(root)
    target = root / SCENARIO
    if target.exists():
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    target.mkdir(parents=True)
    print(f"ROOT={root}")
    print(f"PREPARE_PASS scenario={SCENARIO}")
    return root


def build_seed_prompt() -> str:
    return (
        "这是 P1.2 大上下文连续性测试的第一轮。"
        f"只在当前 Codex 对话上下文中记住合成令牌 {TOKEN}。"
        "不要把令牌写入文件，不要调用任何工具，不要解释。"
        "只回复 LARGE_CONTEXT_READY。"
    )


def _deterministic_payload(round_index: int, target_bytes: int) -> str:
    if target_bytes < 1024:
        raise ValueError("target_bytes must be >= 1024")
    chunks: list[str] = []
    size = 0
    item = 0
    while size < target_bytes:
        digest = hashlib.sha256(f"p1.2:{round_index}:{item}".encode()).hexdigest()
        line = f"segment-{round_index:02d}-{item:06d} {digest}\n"
        chunks.append(line)
        size += len(line.encode("ascii"))
        item += 1
    raw = "".join(chunks).encode("ascii")[:target_bytes]
    return raw.decode("ascii", errors="strict")


def build_filler_prompt(round_index: int, target_bytes: int) -> str:
    ack = f"LARGE_CONTEXT_FILLER_ACK_{round_index:02d}"
    payload = _deterministic_payload(round_index, target_bytes)
    prompt = (
        f"P1.2 synthetic context filler round {round_index}.\n"
        "Do not call tools. Do not search files, logs, memory stores, or local session history. "
        "Do not repeat or ask for any synthetic token from earlier turns. "
        "Treat the following deterministic material as context that must pass through the same Codex thread.\n"
        "--- BEGIN SYNTHETIC FILLER ---\n"
        + payload
        + "\n--- END SYNTHETIC FILLER ---\n"
        + f"Reply with exactly {ack} and nothing else."
    )
    if TOKEN in prompt:
        raise AssertionError("filler prompt leaked the context token")
    return prompt


def build_final_prompt() -> str:
    prompt = (
        "这是同一个 P1.2 Codex 对话的最终恢复轮。不要向我询问第一轮的合成令牌，"
        "也不要从本机 Codex session/history、~/.codex、~/.uwa、日志、SQLite、PROMPTS.md 或其他文件中搜索令牌。"
        f"第一步必须通过客户端 exec_command 在当前工作区执行 pwd && test -f {MARKER} && test -d {SCENARIO}。"
        "如果工作区校验失败，只回复 ACCEPTANCE_WORKSPACE_MISMATCH。"
        f"校验成功后，只使用你从第一轮对话上下文保留的合成令牌，创建 {RESULT_RELATIVE.as_posix()}，"
        "文件必须精确包含该令牌和一个换行。然后实际读取该文件确认内容。"
        "不要读取任何其他可能保存会话或提示历史的路径。完成后只回复 LARGE_CONTEXT_PASS。"
    )
    if TOKEN in prompt:
        raise AssertionError("final prompt must not repeat the token")
    return prompt


def parse_exec_jsonl(text: str, returncode: int = 0) -> ExecObservation:
    observation = ExecObservation(returncode=returncode, raw=text)
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "thread.started":
            thread_id = event.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                observation.thread_ids.append(thread_id)
        elif event_type == "turn.completed":
            usage = event.get("usage")
            if isinstance(usage, dict):
                input_tokens = usage.get("input_tokens")
                output_tokens = usage.get("output_tokens")
                if isinstance(input_tokens, int):
                    observation.input_tokens.append(input_tokens)
                if isinstance(output_tokens, int):
                    observation.output_tokens.append(output_tokens)
        elif event_type in {"item.started", "item.updated", "item.completed"}:
            item = event.get("item")
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "agent_message" and event_type == "item.completed":
                text_value = item.get("text")
                if isinstance(text_value, str):
                    observation.agent_messages.append(text_value)
            elif item_type == "command_execution" and event_type == "item.completed":
                command = item.get("command")
                if isinstance(command, str):
                    observation.commands.append(command)
            elif item_type == "file_change" and event_type == "item.completed":
                observation.file_change_count += 1
            elif item_type == "mcp_tool_call" and event_type == "item.completed":
                observation.mcp_call_count += 1
    return observation


def _write_private_trace(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _chmod_private(path.parent, 0o700)
    path.write_text(text, encoding="utf-8")
    _chmod_private(path, 0o600)


def _run_codex_turn(
    *,
    codex: str,
    root: Path,
    prompt: str,
    trace_path: Path,
    thread_id: str | None,
    timeout_sec: int,
) -> ExecObservation:
    args = [codex, "exec", "--json", "--color", "never"]
    if thread_id is None:
        args.append("-")
    else:
        args.extend(["resume", thread_id, "-"])

    try:
        result = subprocess.run(
            args,
            cwd=str(root),
            input=prompt,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        output = str(exc.stdout or "") + "\nTIMEOUT\n"
        _write_private_trace(trace_path, output)
        raise RuntimeError(f"Codex turn timed out after {timeout_sec}s") from exc

    _write_private_trace(trace_path, result.stdout)
    observation = parse_exec_jsonl(result.stdout, result.returncode)
    if result.returncode != 0:
        raise RuntimeError(
            f"Codex turn failed rc={result.returncode}; private trace={trace_path}"
        )
    return observation


def scan_log_delta(path: Path, offset: int) -> LogEvidence:
    if not path.exists():
        return LogEvidence(offset, 0, 0, False)
    size = path.stat().st_size
    log_reset = size < offset
    start = 0 if log_reset else offset
    with path.open("rb") as handle:
        handle.seek(start)
        data = handle.read()
    text = data.decode("utf-8", errors="replace")
    return LogEvidence(
        next_offset=size,
        route_markers=text.count(COMPACT_ROUTE_MARKER),
        success_markers=text.count(COMPACT_SUCCESS_MARKER),
        log_reset=log_reset,
    )


def _query_context_window() -> int | None:
    url = "http://127.0.0.1:8199/v1/models?client_version=0.153.4"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return None
    for model in models:
        if isinstance(model, dict) and model.get("slug") == "chatgpt":
            value = model.get("context_window")
            if isinstance(value, int):
                return value
    return None


def _workspace_contains_token(root: Path) -> list[str]:
    hits: list[str] = []
    token_bytes = TOKEN.encode("utf-8")
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            if path.stat().st_size > 2_000_000:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if token_bytes in data:
            hits.append(path.relative_to(root).as_posix())
    return hits


def _final_commands_safe(commands: Iterable[str]) -> bool:
    forbidden = (
        ".codex",
        ".uwa/",
        ".uwa\\",
        "rollout",
        "sqlite",
        "PROMPTS.md",
        "mdfind ",
        "find ~",
        "grep -R ~",
        "rg ",
    )
    return all(not any(term in command for term in forbidden) for command in commands)


def _new_trace_dir() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = DEFAULT_PRIVATE_TRACE_ROOT / timestamp
    path.mkdir(parents=True, exist_ok=False, mode=0o700)
    _chmod_private(path, 0o700)
    return path


def _write_evidence(root: Path, evidence: dict[str, Any]) -> None:
    path = root / EVIDENCE_RELATIVE
    path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _verify_thread(observation: ExecObservation, thread_id: str) -> bool:
    return all(observed == thread_id for observed in observation.thread_ids)


def run(
    root: Path,
    *,
    codex: str,
    uwa_log: Path,
    filler_bytes: int,
    max_rounds: int,
    post_compact_rounds: int,
    timeout_sec: int,
) -> int:
    root = prepare(root)
    codex_path = shutil.which(codex) if os.sep not in codex else codex
    if not codex_path or not Path(codex_path).exists():
        print(f"RUN_FAIL codex_not_found={codex}")
        return 1

    context_window = _query_context_window()
    if context_window is None:
        print("RUN_FAIL UWA model catalog unavailable or chatgpt context_window missing")
        return 1

    token_hits = _workspace_contains_token(root)
    if token_hits:
        print(f"RUN_FAIL token_already_in_workspace={token_hits}")
        return 1

    trace_dir = _new_trace_dir()
    log_offset = uwa_log.stat().st_size if uwa_log.exists() else 0
    total_route_markers = 0
    total_success_markers = 0
    log_reset_observed = False
    usage_input_tokens: list[int] = []
    usage_output_tokens: list[int] = []
    filler_acks_exact = True
    no_prefinal_tool_effects = True
    thread_match = True
    total_filler_bytes = 0
    first_compact_round: int | None = None

    print(f"ROOT={root}")
    print(f"CONTEXT_WINDOW={context_window}")
    print(f"FILLER_BYTES_PER_ROUND={filler_bytes}")
    print(f"MAX_ROUNDS={max_rounds}")
    print(f"PRIVATE_TRACE_DIR={trace_dir}")

    try:
        seed = _run_codex_turn(
            codex=str(codex_path),
            root=root,
            prompt=build_seed_prompt(),
            trace_path=trace_dir / "turn-00-seed.jsonl",
            thread_id=None,
            timeout_sec=timeout_sec,
        )
    except RuntimeError as exc:
        print(f"RUN_FAIL {exc}")
        return 1

    if not seed.thread_ids:
        print("RUN_FAIL seed_thread_id_missing")
        return 1
    thread_id = seed.thread_ids[0]
    seed_exact = seed.final_message == "LARGE_CONTEXT_READY"
    no_prefinal_tool_effects &= seed.tool_effect_count == 0
    thread_match &= _verify_thread(seed, thread_id)
    usage_input_tokens.extend(seed.input_tokens)
    usage_output_tokens.extend(seed.output_tokens)

    log_evidence = scan_log_delta(uwa_log, log_offset)
    log_offset = log_evidence.next_offset
    total_route_markers += log_evidence.route_markers
    total_success_markers += log_evidence.success_markers
    log_reset_observed |= log_evidence.log_reset

    print(f"SEED_REPLY_EXACT={'YES' if seed_exact else 'NO'}")
    print(f"SEED_TOOL_EFFECTS={seed.tool_effect_count}")

    if not seed_exact or not no_prefinal_tool_effects:
        print("RUN_FAIL seed_contract")
        return 1

    rounds_completed = 0
    compact_seen_at: int | None = None
    extra_rounds_remaining: int | None = None

    for round_index in range(1, max_rounds + 1):
        prompt = build_filler_prompt(round_index, filler_bytes)
        total_filler_bytes += len(_deterministic_payload(round_index, filler_bytes).encode("ascii"))
        try:
            observation = _run_codex_turn(
                codex=str(codex_path),
                root=root,
                prompt=prompt,
                trace_path=trace_dir / f"turn-{round_index:02d}-filler.jsonl",
                thread_id=thread_id,
                timeout_sec=timeout_sec,
            )
        except RuntimeError as exc:
            print(f"RUN_FAIL round={round_index} {exc}")
            return 1

        rounds_completed += 1
        expected_ack = f"LARGE_CONTEXT_FILLER_ACK_{round_index:02d}"
        ack_exact = observation.final_message == expected_ack
        filler_acks_exact &= ack_exact
        no_prefinal_tool_effects &= observation.tool_effect_count == 0
        thread_match &= _verify_thread(observation, thread_id)
        usage_input_tokens.extend(observation.input_tokens)
        usage_output_tokens.extend(observation.output_tokens)

        log_evidence = scan_log_delta(uwa_log, log_offset)
        log_offset = log_evidence.next_offset
        total_route_markers += log_evidence.route_markers
        total_success_markers += log_evidence.success_markers
        log_reset_observed |= log_evidence.log_reset

        if log_evidence.success_markers and first_compact_round is None:
            first_compact_round = round_index
            compact_seen_at = round_index
            extra_rounds_remaining = post_compact_rounds

        last_input = observation.input_tokens[-1] if observation.input_tokens else -1
        print(
            f"ROUND={round_index:02d} ACK_EXACT={'YES' if ack_exact else 'NO'} "
            f"TOOL_EFFECTS={observation.tool_effect_count} INPUT_TOKENS={last_input} "
            f"COMPACT_ROUTE_DELTA={log_evidence.route_markers} "
            f"COMPACT_SUCCESS_DELTA={log_evidence.success_markers}"
        )

        if not ack_exact or observation.tool_effect_count:
            print(f"RUN_FAIL filler_contract round={round_index}")
            return 1

        if compact_seen_at is not None and extra_rounds_remaining is not None:
            if round_index > compact_seen_at:
                extra_rounds_remaining -= 1
            if extra_rounds_remaining <= 0:
                break

    token_hits_before_final = _workspace_contains_token(root)
    workspace_token_clean = not token_hits_before_final
    print(f"TOKEN_LEAK_BEFORE_FINAL={'NO' if workspace_token_clean else 'YES'}")
    if not workspace_token_clean:
        print(f"RUN_FAIL token_leak_paths={token_hits_before_final}")
        return 1

    try:
        final = _run_codex_turn(
            codex=str(codex_path),
            root=root,
            prompt=build_final_prompt(),
            trace_path=trace_dir / "turn-final.jsonl",
            thread_id=thread_id,
            timeout_sec=timeout_sec,
        )
    except RuntimeError as exc:
        print(f"RUN_FAIL final {exc}")
        return 1

    thread_match &= _verify_thread(final, thread_id)
    usage_input_tokens.extend(final.input_tokens)
    usage_output_tokens.extend(final.output_tokens)
    final_reply_exact = final.final_message == "LARGE_CONTEXT_PASS"
    final_tools_used = final.tool_effect_count > 0
    final_commands_safe = _final_commands_safe(final.commands)

    log_evidence = scan_log_delta(uwa_log, log_offset)
    total_route_markers += log_evidence.route_markers
    total_success_markers += log_evidence.success_markers
    log_reset_observed |= log_evidence.log_reset
    if log_evidence.success_markers and first_compact_round is None:
        first_compact_round = rounds_completed + 1

    result_path = root / RESULT_RELATIVE
    result_bytes = result_path.read_bytes() if result_path.exists() else b""
    result_exact = result_bytes == (TOKEN + "\n").encode("utf-8")
    compact_proven = total_success_markers > 0

    evidence: dict[str, Any] = {
        "schema_version": 1,
        "scenario": SCENARIO,
        "context_window_reported": context_window,
        "filler_bytes_per_round": filler_bytes,
        "filler_rounds_completed": rounds_completed,
        "total_filler_bytes": total_filler_bytes,
        "seed_reply_exact": seed_exact,
        "filler_acks_exact": filler_acks_exact,
        "prefinal_tool_effects_zero": no_prefinal_tool_effects,
        "workspace_token_clean_before_final": workspace_token_clean,
        "same_thread_observed": thread_match,
        "compact_route_marker_count": total_route_markers,
        "compact_success_marker_count": total_success_markers,
        "compact_route_observed": total_route_markers > 0,
        "compact_success_observed": compact_proven,
        "first_compact_round": first_compact_round,
        "log_reset_observed": log_reset_observed,
        "turn_input_tokens": usage_input_tokens,
        "turn_output_tokens": usage_output_tokens,
        "final_reply_exact": final_reply_exact,
        "final_tools_used": final_tools_used,
        "final_commands_safe": final_commands_safe,
        "result_exact": result_exact,
        "private_trace_retained": True,
        "private_trace_path_not_recorded": True,
    }
    _write_evidence(root, evidence)

    print(f"SAME_THREAD={'YES' if thread_match else 'NO'}")
    print(f"COMPACT_ROUTE_MARKERS={total_route_markers}")
    print(f"COMPACT_SUCCESS_MARKERS={total_success_markers}")
    print(f"COMPACTION_PROVEN={'YES' if compact_proven else 'NO'}")
    print(f"FINAL_REPLY_EXACT={'YES' if final_reply_exact else 'NO'}")
    print(f"FINAL_TOOLS_USED={'YES' if final_tools_used else 'NO'}")
    print(f"FINAL_COMMANDS_SAFE={'YES' if final_commands_safe else 'NO'}")
    print(f"RESULT_EXACT={'YES' if result_exact else 'NO'}")

    return check(root)


def check(root: Path) -> int:
    root = _guard_root(root)
    evidence_path = root / EVIDENCE_RELATIVE
    result_path = root / RESULT_RELATIVE
    result_bytes = result_path.read_bytes() if result_path.exists() else b""
    result_exact = result_bytes == (TOKEN + "\n").encode("utf-8")

    if not evidence_path.exists():
        print("large_context: FAIL")
        print("reason=missing_evidence")
        return 1
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print("large_context: FAIL")
        print("reason=invalid_evidence_json")
        return 1

    required = {
        "seed_reply_exact": True,
        "filler_acks_exact": True,
        "prefinal_tool_effects_zero": True,
        "workspace_token_clean_before_final": True,
        "same_thread_observed": True,
        "compact_success_observed": True,
        "final_reply_exact": True,
        "final_tools_used": True,
        "final_commands_safe": True,
        "result_exact": True,
    }
    failures = [key for key, expected in required.items() if evidence.get(key) is not expected]
    if not result_exact:
        failures.append("result_bytes")
    if not isinstance(evidence.get("filler_rounds_completed"), int) or evidence.get("filler_rounds_completed", 0) < 1:
        failures.append("filler_rounds_completed")
    if not isinstance(evidence.get("total_filler_bytes"), int) or evidence.get("total_filler_bytes", 0) < 1:
        failures.append("total_filler_bytes")
    if not isinstance(evidence.get("compact_success_marker_count"), int) or evidence.get("compact_success_marker_count", 0) < 1:
        failures.append("compact_success_marker_count")

    if failures:
        stress_ok = (
            result_exact
            and evidence.get("seed_reply_exact") is True
            and evidence.get("filler_acks_exact") is True
            and evidence.get("workspace_token_clean_before_final") is True
            and evidence.get("same_thread_observed") is True
            and evidence.get("final_reply_exact") is True
        )
        if stress_ok and evidence.get("compact_success_observed") is not True:
            print("large_context: STRESS_PASS_COMPACTION_UNPROVEN")
            print(f"failures={sorted(set(failures))}")
            return 2
        print("large_context: FAIL")
        print(f"failures={sorted(set(failures))}")
        return 1

    print("large_context: PASS")
    print("COMPACTION_EVIDENCE=PASS")
    print("LARGE_CONTEXT_PASS")
    return 0


def show_prompts(filler_bytes: int) -> None:
    print("===== large_context_seed =====")
    print(build_seed_prompt())
    print()
    print("===== large_context_filler_01 =====")
    print(build_filler_prompt(1, filler_bytes))
    print()
    print("===== large_context_final =====")
    print(build_final_prompt())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run", "check", "prompts"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--uwa-log", type=Path, default=DEFAULT_UWA_LOG)
    parser.add_argument("--filler-bytes", type=int, default=DEFAULT_FILLER_BYTES)
    parser.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS)
    parser.add_argument("--post-compact-rounds", type=int, default=DEFAULT_POST_COMPACT_ROUNDS)
    parser.add_argument("--timeout-sec", type=int, default=DEFAULT_TIMEOUT_SEC)
    args = parser.parse_args()

    if args.filler_bytes < 1024:
        raise SystemExit("--filler-bytes must be >= 1024")
    if args.max_rounds < 1:
        raise SystemExit("--max-rounds must be >= 1")
    if args.post_compact_rounds < 0:
        raise SystemExit("--post-compact-rounds must be >= 0")

    if args.command == "prepare":
        prepare(args.root)
        return 0
    if args.command == "prompts":
        show_prompts(args.filler_bytes)
        return 0
    if args.command == "check":
        return check(args.root)
    return run(
        args.root,
        codex=args.codex,
        uwa_log=args.uwa_log.expanduser(),
        filler_bytes=args.filler_bytes,
        max_rounds=args.max_rounds,
        post_compact_rounds=args.post_compact_rounds,
        timeout_sec=args.timeout_sec,
    )


if __name__ == "__main__":
    raise SystemExit(main())
