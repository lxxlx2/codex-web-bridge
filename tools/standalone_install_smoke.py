#!/usr/bin/env python3
"""Clean-checkout install/provider/rollback smoke for Codex Web Bridge rc.1.

This is a local macOS release gate. It creates a detached worktree and a
temporary HOME, installs the public wrappers from that clean checkout, prepares
the checkout-local runtime before touching the active listener, runs one small
real Codex request through the checkout-owned listener, verifies the official
rollback in the isolated HOME, then switches back and stops cleanly.

It never copies or prints authentication material. Existing user Codex config is
not modified because all wrapper/provider commands run with an isolated HOME.
If TCP 8199 is already served by the current checkout, the runner temporarily
stops it only after the clean checkout dependency bootstrap succeeds, then
restores it in ``finally``. Foreign listeners are never touched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

try:
    from tools import codex_uwa_lifecycle as lifecycle
except ModuleNotFoundError:
    import codex_uwa_lifecycle as lifecycle


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRIVATE_ROOT = Path.home() / ".uwa" / "standalone-s4"
DEFAULT_RESULT = DEFAULT_PRIVATE_ROOT / "install-smoke-result.txt"
DEFAULT_BOOTSTRAP_TIMEOUT_SEC = 900
SMOKE_REPLY = "INSTALL_SMOKE_PASS"


class SmokeFailure(RuntimeError):
    def __init__(self, gate: str, detail: str) -> None:
        super().__init__(detail)
        self.gate = gate
        self.detail = detail


def _run(
    args: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    timeout_sec: int = 120,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(args),
            cwd=str(cwd),
            env=env,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SmokeFailure("subprocess_timeout", f"timeout={timeout_sec}s") from exc


def _git(*args: str, cwd: Path = REPO_ROOT, timeout_sec: int = 60) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd=cwd, timeout_sec=timeout_sec)


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


def _private_dir(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = root.expanduser()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    candidate = root / f"install-smoke-{stamp}"
    suffix = 0
    while candidate.exists():
        suffix += 1
        candidate = root / f"install-smoke-{stamp}-{suffix}"
    candidate.mkdir(mode=0o700)
    return candidate


def _sha256_or_absent(path: Path) -> str:
    if not path.is_file():
        return "ABSENT"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_commit() -> str:
    result = _git("rev-parse", "HEAD")
    if result.returncode != 0 or not result.stdout.strip():
        raise SmokeFailure("git_head", "unable_to_resolve_head")
    return result.stdout.strip()


def _require_clean_current_checkout() -> None:
    if platform.system() != "Darwin":
        raise SmokeFailure("platform", "macOS_required")
    status = _git("status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0 or status.stdout.strip():
        raise SmokeFailure("worktree", "source_checkout_dirty")
    if shutil.which("codex") is None:
        raise SmokeFailure("codex_cli", "codex_not_found")


def _parse_codex_final(text: str) -> str:
    messages: list[str] = []
    for raw in text.splitlines():
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "agent_message":
            continue
        value = item.get("text")
        if isinstance(value, str):
            messages.append(value.strip())
    return messages[-1] if messages else ""


def _default_pip_cache() -> Path:
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Caches" / "pip"
    return Path.home() / ".cache" / "pip"


def _isolated_env(home: Path, bin_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("CODEX_HOME", None)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env.setdefault("PIP_CACHE_DIR", str(_default_pip_cache()))
    return env


def _write_desktop_stubs(bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    scripts = {
        "osascript": "#!/bin/sh\nexit 0\n",
        "open": "#!/bin/sh\nexit 0\n",
        # Provider switch checks whether desktop apps are running before trying
        # to quit them. The isolated smoke must never touch real user apps.
        "pgrep": "#!/bin/sh\nexit 1\n",
    }
    for name, body in scripts.items():
        path = bin_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)


def _validate_wrapper_roots(bin_dir: Path, checkout: Path) -> None:
    expected = f"ROOT={shlex.quote(str(checkout.resolve()))}"
    for name in ("codex-uwa", "codex-uwa-stop", "codex-official", "codex-uwa-status"):
        path = bin_dir / name
        if not path.is_file():
            raise SmokeFailure("wrapper_install", f"missing={name}")
        text = path.read_text(encoding="utf-8")
        if expected not in text:
            raise SmokeFailure("wrapper_root", f"wrong_root={name}")
        if "universal-web-api" in text:
            raise SmokeFailure("wrapper_root", f"legacy_root={name}")


def _provider_state(config: Path) -> dict[str, Any]:
    try:
        parsed = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SmokeFailure("provider_config", "invalid_config") from exc
    return parsed


def _require_uwa_config(config: Path) -> None:
    parsed = _provider_state(config)
    expected = {
        "model_provider": "uwa",
        "model": "chatgpt",
        "model_reasoning_effort": "high",
        "model_auto_compact_token_limit_scope": "body_after_prefix",
    }
    for key, value in expected.items():
        if parsed.get(key) != value:
            raise SmokeFailure("provider_config", f"{key}_mismatch")


def _require_official_restore(config: Path) -> None:
    parsed = _provider_state(config)
    for key in ("model_provider", "model", "model_reasoning_effort"):
        if key in parsed:
            raise SmokeFailure("official_rollback", f"pin_not_removed={key}")
    if parsed.get("approval_policy") != "never":
        raise SmokeFailure("official_rollback", "approval_policy_not_restored")
    if parsed.get("sandbox_mode") != "read-only":
        raise SmokeFailure("official_rollback", "sandbox_mode_not_restored")
    if parsed.get("notify") != ["smoke"]:
        raise SmokeFailure("official_rollback", "unrelated_config_changed")


def _write_baseline_config(home: Path) -> Path:
    path = home / ".codex" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'approval_policy = "never"\n'
        'sandbox_mode = "read-only"\n'
        'notify = ["smoke"]\n',
        encoding="utf-8",
    )
    return path


def _prepare_worktree(checkout: Path, candidate: str, private_dir: Path) -> None:
    result = _git(
        "worktree",
        "add",
        "--detach",
        str(checkout),
        candidate,
        timeout_sec=120,
    )
    _write_private(private_dir / "worktree-add.log", result.stdout)
    if result.returncode != 0:
        raise SmokeFailure("clean_checkout", f"rc={result.returncode}")


def _remove_worktree(checkout: Path, private_dir: Path) -> None:
    result = _git(
        "worktree",
        "remove",
        "--force",
        str(checkout),
        timeout_sec=120,
    )
    _write_private(private_dir / "worktree-remove.log", result.stdout)
    if result.returncode != 0:
        shutil.rmtree(checkout, ignore_errors=True)
        _git("worktree", "prune", timeout_sec=60)


def _stop_original_listener_if_owned() -> bool:
    pids = lifecycle.listener_pids()
    if not pids:
        return False
    lifecycle.require_owned_listeners(pids, repo_root=REPO_ROOT)
    lifecycle.stop_uwa(repo_root=REPO_ROOT)
    return True


def _stop_checkout_listener_if_present(checkout: Path) -> None:
    pids = lifecycle.listener_pids()
    if not pids:
        return
    try:
        lifecycle.require_owned_listeners(pids, repo_root=checkout)
    except RuntimeError:
        return
    lifecycle.stop_uwa(repo_root=checkout)


def _restore_original_listener(was_running: bool) -> None:
    if not was_running:
        return
    if lifecycle.listener_pids():
        return
    lifecycle.start_uwa(repo_root=REPO_ROOT)


def _run_wrapper(
    path: Path,
    *,
    checkout: Path,
    env: dict[str, str],
    private_dir: Path,
    log_name: str,
    timeout_sec: int = 180,
) -> subprocess.CompletedProcess[str]:
    result = _run(
        [str(path)],
        cwd=checkout,
        env=env,
        timeout_sec=timeout_sec,
    )
    _write_private(private_dir / log_name, result.stdout)
    return result


def _preserve_checkout_uwa_log(
    home: Path | None,
    private_dir: Path,
    name: str,
) -> bool:
    if home is None:
        return False
    source = home / ".uwa" / "uwa.log"
    if not source.is_file():
        return False
    try:
        text = source.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    _write_private(private_dir / name, text)
    return True


def _run_dependency_bootstrap(
    *,
    checkout: Path,
    env: dict[str, str],
    private_dir: Path,
    timeout_sec: int,
) -> None:
    try:
        result = _run(
            [sys.executable, str(checkout / "start.py"), "--bootstrap-only"],
            cwd=checkout,
            env=env,
            timeout_sec=timeout_sec,
        )
    except SmokeFailure as exc:
        if exc.gate == "subprocess_timeout":
            raise SmokeFailure(
                "dependency_bootstrap",
                f"timeout={timeout_sec}s",
            ) from exc
        raise
    _write_private(private_dir / "dependency-bootstrap.log", result.stdout)
    if result.returncode != 0:
        raise SmokeFailure("dependency_bootstrap", f"rc={result.returncode}")
    python = checkout / ".venv" / "bin" / "python"
    stamp = checkout / ".venv" / ".requirements.sha256"
    if not python.is_file() or not stamp.is_file():
        raise SmokeFailure("dependency_bootstrap", "runtime_not_prepared")


def _run_surface_preflight(*, checkout: Path, private_dir: Path) -> None:
    python = checkout / ".venv" / "bin" / "python"
    if not python.is_file():
        raise SmokeFailure("listener_start", "checkout_venv_missing")
    result = _run(
        [
            str(python),
            str(checkout / "tools" / "chatgpt_surface_preflight.py"),
            "--timeout-sec",
            "12",
        ],
        cwd=checkout,
        timeout_sec=45,
    )
    _write_private(private_dir / "surface-preflight.log", result.stdout)
    if result.returncode != 0:
        raise SmokeFailure("surface_preflight", f"rc={result.returncode}")


def _run_basic_codex(
    *,
    checkout: Path,
    env: dict[str, str],
    private_dir: Path,
    timeout_sec: int,
) -> None:
    codex = shutil.which("codex", path=env.get("PATH")) or shutil.which("codex")
    if not codex:
        raise SmokeFailure("codex_cli", "codex_not_found")
    prompt = (
        "This is a release install smoke test. Do not use tools. "
        f"Reply with exactly {SMOKE_REPLY} and nothing else."
    )
    result = _run(
        [
            codex,
            "exec",
            "--json",
            "--color",
            "never",
            "--skip-git-repo-check",
            "-",
        ],
        cwd=checkout,
        env=env,
        input_text=prompt,
        timeout_sec=timeout_sec,
    )
    _write_private(private_dir / "basic-codex.jsonl", result.stdout)
    if result.returncode != 0:
        raise SmokeFailure("basic_codex_request", f"rc={result.returncode}")
    if _parse_codex_final(result.stdout) != SMOKE_REPLY:
        raise SmokeFailure("basic_codex_request", "final_reply_mismatch")


def run(
    *,
    private_root: Path,
    result_path: Path,
    request_timeout_sec: int = 180,
    bootstrap_timeout_sec: int = DEFAULT_BOOTSTRAP_TIMEOUT_SEC,
) -> int:
    private_dir = _private_dir(private_root)
    candidate = ""
    original_listener_running = False
    checkout: Path | None = None
    home: Path | None = None
    actual_auth = Path.home() / ".codex" / "auth.json"
    auth_before = _sha256_or_absent(actual_auth)

    try:
        _require_clean_current_checkout()
        candidate = _candidate_commit()

        temp_root = Path(tempfile.mkdtemp(prefix="codex-web-bridge-smoke-"))
        checkout = temp_root / "checkout"
        home = temp_root / "home"
        bin_dir = temp_root / "bin"
        home.mkdir(parents=True, exist_ok=True)
        _write_desktop_stubs(bin_dir)
        config = _write_baseline_config(home)
        env = _isolated_env(home, bin_dir)

        _prepare_worktree(checkout, candidate, private_dir)

        install = _run(
            [
                sys.executable,
                str(checkout / "tools" / "install_codex_uwa_commands.py"),
                "--bin-dir",
                str(bin_dir),
            ],
            cwd=checkout,
            env=env,
            timeout_sec=60,
        )
        _write_private(private_dir / "install-wrappers.log", install.stdout)
        if install.returncode != 0:
            raise SmokeFailure("wrapper_install", f"rc={install.returncode}")
        _validate_wrapper_roots(bin_dir, checkout)

        # Dependency installation is a separate release gate. Run it while the
        # user's existing listener is still available, then take over TCP 8199
        # only after the clean checkout runtime is ready.
        _run_dependency_bootstrap(
            checkout=checkout,
            env=env,
            private_dir=private_dir,
            timeout_sec=bootstrap_timeout_sec,
        )

        original_listener_running = _stop_original_listener_if_owned()

        start = _run_wrapper(
            bin_dir / "codex-uwa",
            checkout=checkout,
            env=env,
            private_dir=private_dir,
            log_name="codex-uwa-first.log",
            timeout_sec=180,
        )
        _preserve_checkout_uwa_log(home, private_dir, "checkout-uwa-first.log")
        if start.returncode != 0:
            raise SmokeFailure("uwa_switch", f"rc={start.returncode}")
        _require_uwa_config(config)

        pids = lifecycle.listener_pids()
        if not pids:
            raise SmokeFailure("listener_start", "listener_missing")
        lifecycle.require_owned_listeners(pids, repo_root=checkout)
        if not lifecycle.health_ok():
            raise SmokeFailure("listener_start", "health_not_ready")

        status = _run_wrapper(
            bin_dir / "codex-uwa-status",
            checkout=checkout,
            env=env,
            private_dir=private_dir,
            log_name="codex-uwa-status.log",
            timeout_sec=60,
        )
        if status.returncode != 0 or "STATUS=HEALTHY" not in status.stdout:
            raise SmokeFailure("uwa_status", "status_not_healthy")

        _run_surface_preflight(
            checkout=checkout,
            private_dir=private_dir,
        )
        _run_basic_codex(
            checkout=checkout,
            env=env,
            private_dir=private_dir,
            timeout_sec=request_timeout_sec,
        )

        official = _run_wrapper(
            bin_dir / "codex-official",
            checkout=checkout,
            env=env,
            private_dir=private_dir,
            log_name="codex-official.log",
            timeout_sec=120,
        )
        if official.returncode != 0:
            raise SmokeFailure("official_rollback", f"rc={official.returncode}")
        _require_official_restore(config)
        if lifecycle.listener_pids():
            raise SmokeFailure("official_rollback", "listener_not_stopped")

        second = _run_wrapper(
            bin_dir / "codex-uwa",
            checkout=checkout,
            env=env,
            private_dir=private_dir,
            log_name="codex-uwa-second.log",
            timeout_sec=180,
        )
        _preserve_checkout_uwa_log(home, private_dir, "checkout-uwa-second.log")
        if second.returncode != 0:
            raise SmokeFailure("repeat_switch", f"rc={second.returncode}")
        _require_uwa_config(config)

        stopped = _run_wrapper(
            bin_dir / "codex-uwa-stop",
            checkout=checkout,
            env=env,
            private_dir=private_dir,
            log_name="codex-uwa-stop.log",
            timeout_sec=120,
        )
        if stopped.returncode != 0 or lifecycle.listener_pids():
            raise SmokeFailure("repeat_switch", "final_stop_failed")

        auth_after = _sha256_or_absent(actual_auth)
        if auth_after != auth_before:
            raise SmokeFailure("authentication", "user_auth_changed")

        text = (
            "INSTALL_SMOKE=PASS\n"
            "DEPENDENCY_BOOTSTRAP=PASS\n"
            "OFFICIAL_ROLLBACK=PASS\n"
            "BASIC_CODEX_REQUEST=PASS\n"
            "AUTH=UNCHANGED\n"
            "WRAPPER_ROOT=PASS\n"
            "LISTENER_OWNERSHIP=PASS\n"
            f"candidate_commit={candidate}\n"
        )
        _write_private(result_path.expanduser(), text)
        print("INSTALL_SMOKE=PASS", flush=True)
        print("DEPENDENCY_BOOTSTRAP=PASS", flush=True)
        print("OFFICIAL_ROLLBACK=PASS", flush=True)
        print("BASIC_CODEX_REQUEST=PASS", flush=True)
        print("AUTH=UNCHANGED", flush=True)
        return 0
    except (SmokeFailure, RuntimeError) as exc:
        gate = exc.gate if isinstance(exc, SmokeFailure) else "lifecycle"
        detail = exc.detail if isinstance(exc, SmokeFailure) else exc.__class__.__name__
        _write_private(
            result_path.expanduser(),
            "INSTALL_SMOKE=FAIL\n"
            f"FAILURE_CLASS={gate}\n"
            f"DETAIL={detail}\n"
            + (f"candidate_commit={candidate}\n" if candidate else ""),
        )
        print("INSTALL_SMOKE=FAIL", flush=True)
        print(f"FAILURE_CLASS={gate}", flush=True)
        print(f"FAILURE_DETAIL={detail}", flush=True)
        print("PRIVATE_EVIDENCE_RECORDED=YES", flush=True)
        return 1
    finally:
        try:
            _preserve_checkout_uwa_log(home, private_dir, "checkout-uwa-final.log")
        except Exception:
            pass
        try:
            if checkout is not None:
                _stop_checkout_listener_if_present(checkout)
        except Exception:
            pass
        try:
            _restore_original_listener(original_listener_running)
        except Exception:
            pass
        if checkout is not None and checkout.exists():
            try:
                _remove_worktree(checkout, private_dir)
            except Exception:
                pass
        temp_root_value = locals().get("temp_root")
        if isinstance(temp_root_value, Path):
            shutil.rmtree(temp_root_value, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--private-root",
        type=Path,
        default=DEFAULT_PRIVATE_ROOT,
    )
    parser.add_argument(
        "--result",
        type=Path,
        default=DEFAULT_RESULT,
    )
    parser.add_argument(
        "--request-timeout-sec",
        type=int,
        default=180,
    )
    parser.add_argument(
        "--bootstrap-timeout-sec",
        type=int,
        default=DEFAULT_BOOTSTRAP_TIMEOUT_SEC,
    )
    args = parser.parse_args()
    if args.request_timeout_sec < 60:
        raise SystemExit("request timeout must be at least 60 seconds")
    if args.bootstrap_timeout_sec < 300:
        raise SystemExit("bootstrap timeout must be at least 300 seconds")
    return run(
        private_root=args.private_root,
        result_path=args.result,
        request_timeout_sec=args.request_timeout_sec,
        bootstrap_timeout_sec=args.bootstrap_timeout_sec,
    )


if __name__ == "__main__":
    raise SystemExit(main())
