#!/usr/bin/env python3
"""Operator-assisted release gate for real Codex Desktop usage.

The existing S3 live gate proves the CLI protocol/continuity/compaction path and
keeps Codex Desktop quiet so evidence is attributable. This gate complements it
with a real Codex Desktop run against the same standalone listener.

The gate is intentionally two-phase:

* ``prepare`` configures UWA, requires a clean ChatGPT Web surface, prepares an
  isolated acceptance workspace, records a route-audit marker, and opens Codex
  Desktop on that workspace. It prints three synthetic acceptance prompts.
* The operator runs those prompts in Codex Desktop as instructed.
* ``verify`` checks the resulting files/tests, requires UWA/chatgpt/high route
  evidence after the marker, requires request-manager cleanup, and writes a
  candidate-bound private PASS result.

No private prompt/tool body or raw thread identifier is copied into the repo.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# The release tools historically import sibling modules as top-level modules
# because they are normally executed as scripts from tools/. Tests import this
# gate as ``tools.standalone_desktop_e2e_gate`` instead. Put the tools directory
# on sys.path once so both invocation modes resolve the exact same modules.
TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import codex_desktop_acceptance as desktop
import codex_route_audit as route_audit
import standalone_s3_live_acceptance as s3
import standalone_s3_live_core as core


DEFAULT_ACCEPTANCE_ROOT = Path.home() / "uwa-codex-acceptance"
DEFAULT_PRIVATE_ROOT = Path.home() / ".uwa" / "standalone-desktop-e2e"
DEFAULT_STATE = DEFAULT_PRIVATE_ROOT / "state.json"
DEFAULT_RESULT = DEFAULT_PRIVATE_ROOT / "result.txt"


class GateFailure(RuntimeError):
    def __init__(self, gate: str, detail: str = "") -> None:
        super().__init__(detail or gate)
        self.gate = gate
        self.detail = detail


def _candidate_commit() -> str:
    result = core._git("rev-parse", "HEAD")
    if result.returncode != 0 or not result.stdout.strip():
        raise GateFailure("git_head", "unable_to_resolve_candidate_commit")
    return result.stdout.strip()


def _desktop_running() -> bool:
    """Return the real macOS application state, with a process fallback."""

    if platform.system() != "Darwin":
        return False

    try:
        result = subprocess.run(
            ["osascript", "-e", 'application "Codex" is running'],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=5,
        )
        value = result.stdout.strip().lower()
        if result.returncode == 0 and value in {"true", "false"}:
            return value == "true"
    except (OSError, subprocess.TimeoutExpired):
        pass

    try:
        result = subprocess.run(
            ["pgrep", "-f", r"/Codex\.app/Contents/"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _open_desktop(root: Path) -> None:
    if platform.system() != "Darwin":
        raise GateFailure("platform", "macOS_required")

    result = subprocess.run(
        ["open", "-a", "Codex"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GateFailure("desktop_launch", "open_failed")

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if _desktop_running():
            break
        time.sleep(0.25)
    else:
        raise GateFailure("desktop_launch", "app_not_running_after_open")

    result = subprocess.run(
        ["open", "-a", "Codex", str(root)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GateFailure("desktop_workspace_open", "open_workspace_failed")


def _write_json_private(path: Path, payload: dict[str, Any]) -> None:
    core._write_private(
        path,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )


def _read_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateFailure("desktop_state", "state_missing_or_invalid") from exc
    if not isinstance(data, dict):
        raise GateFailure("desktop_state", "state_invalid")
    return data


def _prepare_workspace(root: Path) -> None:
    with _silence_stdout():
        desktop.prepare(root, "context")
        if desktop.preflight(root, "context") != 0:
            raise GateFailure("desktop_workspace", "context_preflight_failed")
        desktop.prepare(root, "multi_file")
        if desktop.preflight(root, "multi_file") != 0:
            raise GateFailure("desktop_workspace", "multi_file_preflight_failed")


class _silence_stdout:
    def __enter__(self):
        import contextlib
        import io

        self._buffer = io.StringIO()
        self._redirect = contextlib.redirect_stdout(self._buffer)
        return self._redirect.__enter__()

    def __exit__(self, exc_type, exc, tb):
        return self._redirect.__exit__(exc_type, exc, tb)


def _route_gate(marker_epoch: float) -> None:
    try:
        core._route_gate(marker_epoch)
    except core.GateFailure as exc:
        raise GateFailure("desktop_route", exc.detail or exc.gate) from exc


def _scenario_check(root: Path, scenario: str) -> None:
    with _silence_stdout():
        rc = desktop.check(root, scenario)
    if rc != 0:
        raise GateFailure("desktop_result", f"scenario={scenario}")


def _write_result(candidate: str) -> None:
    core._write_private(
        DEFAULT_RESULT,
        "STANDALONE_DESKTOP_E2E=PASS\n"
        "DESKTOP_CONTEXT=PASS\n"
        "DESKTOP_LOCAL_TOOLS=PASS\n"
        "DESKTOP_ROUTE_UWA_CHATGPT_HIGH=PASS\n"
        "DESKTOP_REQUEST_MANAGER_CLEAN=PASS\n"
        f"candidate_commit={candidate}\n",
    )


def prepare(*, acceptance_root: Path, state_path: Path) -> int:
    private_dir = core._private_dir(DEFAULT_PRIVATE_ROOT)
    try:
        core._preflight_repo()
        candidate = _candidate_commit()
        core._configure_uwa_route()
        core._start_standalone_listener()
        core._health_ready(require_clean=True)

        # Do not start a Desktop live run while Web is rate-limited, quota
        # blocked, on Work, dirty, ambiguous, or otherwise not safely ready.
        s3._passive_surface_recheck(private_dir)

        root = acceptance_root.expanduser().resolve()
        _prepare_workspace(root)
        marker_epoch = route_audit.write_marker()
        state = {
            "version": 1,
            "candidate_commit": candidate,
            "acceptance_root": str(root),
            "marker_epoch": marker_epoch,
            "private_dir": str(private_dir),
        }
        _write_json_private(state_path.expanduser(), state)
        _open_desktop(root)

        print("DESKTOP_E2E_PREPARE=PASS", flush=True)
        print(f"candidate_commit={candidate}", flush=True)
        print(f"ACCEPTANCE_ROOT={root}", flush=True)
        print("DESKTOP_APP=OPENED", flush=True)
        print("", flush=True)
        print("===== DESKTOP STEP 1: same thread =====", flush=True)
        print(desktop.PROMPTS["context_1"], flush=True)
        print("", flush=True)
        print("===== DESKTOP STEP 2: same thread =====", flush=True)
        print(desktop.PROMPTS["context_2"], flush=True)
        print("", flush=True)
        print("===== DESKTOP STEP 3: new thread =====", flush=True)
        print(desktop.PROMPTS["multi_file"], flush=True)
        print("", flush=True)
        print("After all three complete, run:", flush=True)
        print(".venv/bin/python tools/standalone_desktop_e2e_gate.py verify", flush=True)
        return 0
    except (GateFailure, core.GateFailure) as exc:
        gate = getattr(exc, "gate", "desktop_prepare")
        detail = getattr(exc, "detail", "") or str(exc)
        print("DESKTOP_E2E_PREPARE=FAIL", flush=True)
        print(f"FAILURE_CLASS={gate}", flush=True)
        if detail:
            print(f"FAILURE_DETAIL={detail}", flush=True)
        return 1


def verify(*, state_path: Path) -> int:
    try:
        state = _read_state(state_path)
        candidate = _candidate_commit()
        if state.get("candidate_commit") != candidate:
            raise GateFailure("desktop_candidate_match", "candidate_sha_mismatch")

        core._preflight_repo()
        core._health_ready(require_clean=True)

        root = Path(str(state.get("acceptance_root") or "")).expanduser().resolve()
        marker_epoch = float(state.get("marker_epoch") or 0.0)
        if marker_epoch <= 0:
            raise GateFailure("desktop_state", "marker_missing")

        _scenario_check(root, "context")
        _scenario_check(root, "multi_file")
        _route_gate(marker_epoch)
        core._wait_request_cleanup()
        core._health_ready(require_clean=True)

        status = core._git("status", "--porcelain=v1", "--untracked-files=all")
        if status.returncode != 0 or status.stdout.strip():
            raise GateFailure("desktop_repo_cleanliness", "repository_changed")

        _write_result(candidate)
        print("DESKTOP_CONTEXT=PASS", flush=True)
        print("DESKTOP_LOCAL_TOOLS=PASS", flush=True)
        print("DESKTOP_ROUTE_UWA_CHATGPT_HIGH=PASS", flush=True)
        print("DESKTOP_REQUEST_MANAGER_CLEAN=PASS", flush=True)
        print(f"DESKTOP_APP_RUNNING={'YES' if _desktop_running() else 'NO'}", flush=True)
        print("STANDALONE_DESKTOP_E2E=PASS", flush=True)
        print(f"candidate_commit={candidate}", flush=True)
        return 0
    except (GateFailure, core.GateFailure) as exc:
        gate = getattr(exc, "gate", "desktop_verify")
        detail = getattr(exc, "detail", "") or str(exc)
        print("STANDALONE_DESKTOP_E2E=FAIL", flush=True)
        print(f"FAILURE_CLASS={gate}", flush=True)
        if detail:
            print(f"FAILURE_DETAIL={detail}", flush=True)
        return 1
    except (TypeError, ValueError) as exc:
        print("STANDALONE_DESKTOP_E2E=FAIL", flush=True)
        print("FAILURE_CLASS=desktop_state", flush=True)
        print(f"FAILURE_DETAIL={exc.__class__.__name__}", flush=True)
        return 1


def status(*, state_path: Path) -> int:
    print(f"DESKTOP_APP_RUNNING={'YES' if _desktop_running() else 'NO'}")
    try:
        payload = core._health_payload()
    except core.GateFailure:
        print("UWA_HEALTH=UNAVAILABLE")
        return 1
    web = payload.get("chatgpt_web") if isinstance(payload.get("chatgpt_web"), dict) else {}
    surface = web.get("surface") if isinstance(web.get("surface"), dict) else {}
    print("UWA_HEALTH=" + str(payload.get("service") or "unknown"))
    print("RUNNING_COUNT=" + str(payload.get("running_count", "unknown")))
    print("SURFACE_KIND=" + str(surface.get("surface_kind") or "unknown"))
    print("SURFACE_READY=" + str(bool(surface.get("surface_ready"))))
    print("BLOCKING_REASON=" + str(surface.get("blocking_reason") or "unknown"))
    print("STATE_PRESENT=" + ("YES" if state_path.expanduser().is_file() else "NO"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "verify", "status"])
    parser.add_argument("--acceptance-root", type=Path, default=DEFAULT_ACCEPTANCE_ROOT)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    args = parser.parse_args()

    if args.action == "prepare":
        return prepare(
            acceptance_root=args.acceptance_root,
            state_path=args.state,
        )
    if args.action == "verify":
        return verify(state_path=args.state)
    return status(state_path=args.state)


if __name__ == "__main__":
    raise SystemExit(main())
