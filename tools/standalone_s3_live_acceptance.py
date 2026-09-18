#!/usr/bin/env python3
"""Release-grade standalone S3 acceptance orchestrator.

This wrapper owns the disposable ChatGPT acceptance target and delegates the
proven S3 continuity/compaction logic to ``standalone_s3_live_core``. The core
is an exact copy of the previously validated runner so release hardening can be
added without rewriting the compaction acceptance logic itself.

Safety:
- only runs on the controlled CDP browser;
- requires request-manager cleanup before target reset;
- never sends a prompt while normalizing the surface;
- never clears unknown composer text;
- never bypasses usage/rate limits;
- temporarily quiets Codex Desktop for deterministic CLI evidence, then restores
  the app if it was running when the gate started;
- stores raw evidence only under the private S3 root.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import standalone_s3_live_core as core


REPO_ROOT = Path(__file__).resolve().parents[1]
CDP_BASE = "http://127.0.0.1:9222"
_EXTERNAL_SURFACE_FAILURES = {
    "chatgpt_work_surface",
    "chatgpt_work_quota_exhausted",
    "chatgpt_usage_exhausted",
    "chatgpt_web_rate_limited",
    "chatgpt_auth_required",
    "chatgpt_challenge",
}

# Backward-compatible exports used by existing non-live runner tests.
GateFailure = core.GateFailure
CodexObservation = core.CodexObservation
_parse_codex_jsonl = core._parse_codex_jsonl
_probe_trigger_reply_acceptable = core._probe_trigger_reply_acceptable
_normalize_remote = core._normalize_remote


def _emit(line: str) -> None:
    print(line, flush=True)


def _candidate_commit() -> str:
    result = core._git("rev-parse", "HEAD")
    if result.returncode != 0 or not result.stdout.strip():
        raise GateFailure("git_head", "unable_to_resolve_candidate_commit")
    return result.stdout.strip()


def _codex_desktop_running() -> bool:
    """Return the real Codex Desktop state on macOS."""

    if sys.platform != "darwin":
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


def _quiet_codex_desktop() -> bool:
    """Quiet Codex Desktop and return whether this runner changed app state."""

    if not _codex_desktop_running():
        return False
    subprocess.run(
        ["osascript", "-e", 'tell application "Codex" to quit'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=10,
    )
    time.sleep(1.0)
    return True


def _restore_codex_desktop(was_running: bool) -> None:
    if sys.platform != "darwin" or was_running is not True:
        return
    subprocess.run(
        ["open", "-a", "Codex"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=10,
    )


def _cdp_json(path: str, *, method: str = "GET", timeout: float = 10.0) -> Any:
    request = urllib.request.Request(CDP_BASE + path, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except (OSError, urllib.error.URLError) as exc:
        raise GateFailure("chatgpt_surface_prepare_failed", "cdp_unavailable") from exc
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise GateFailure("chatgpt_surface_prepare_failed", "invalid_cdp_response") from exc


def _cdp_close(path: str, *, timeout: float = 10.0) -> None:
    request = urllib.request.Request(CDP_BASE + path, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
    except (OSError, urllib.error.URLError) as exc:
        raise GateFailure("chatgpt_surface_prepare_failed", "cdp_close_failed") from exc


def _chatgpt_page_targets() -> list[dict[str, Any]]:
    payload = _cdp_json("/json/list", timeout=5.0)
    if not isinstance(payload, list):
        raise GateFailure("chatgpt_surface_prepare_failed", "invalid_target_list")
    result: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") != "page":
            continue
        url = str(item.get("url") or "")
        if url.startswith("https://chatgpt.com") or url.startswith("https://www.chatgpt.com"):
            result.append(item)
    return result


def _reset_acceptance_chatgpt_target() -> dict[str, Any]:
    core._health_ready(require_clean=True)

    closed = 0
    for item in _chatgpt_page_targets():
        target_id = str(item.get("id") or "").strip()
        if not target_id:
            continue
        try:
            _cdp_close(
                "/json/close/" + urllib.parse.quote(target_id, safe=""),
                timeout=10.0,
            )
            closed += 1
        except GateFailure:
            # A target may disappear while the close request is in flight.
            pass

    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline and _chatgpt_page_targets():
        time.sleep(0.2)
    if _chatgpt_page_targets():
        raise GateFailure("chatgpt_target_ambiguous", "stale_target_close_failed")

    encoded = urllib.parse.quote("https://chatgpt.com/", safe=":/")
    created = _cdp_json("/json/new?" + encoded, method="PUT", timeout=10.0)
    if not isinstance(created, dict) or not str(created.get("id") or "").strip():
        raise GateFailure("chatgpt_target_missing", "fresh_target_create_failed")

    deadline = time.monotonic() + 15.0
    latest: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        latest = _chatgpt_page_targets()
        if len(latest) == 1:
            return {"closed_targets": closed, "fresh_target": True}
        if len(latest) > 1:
            raise GateFailure("chatgpt_target_ambiguous", f"target_count={len(latest)}")
        time.sleep(0.25)

    raise GateFailure("chatgpt_target_missing", "fresh_target_not_visible")


def _parse_surface_preflight(text: str) -> dict[str, Any]:
    prefix = "SURFACE_PREFLIGHT_JSON="
    rows = [line[len(prefix):] for line in text.splitlines() if line.startswith(prefix)]
    if len(rows) != 1:
        raise GateFailure("chatgpt_surface_prepare_failed", "surface_result_missing")
    try:
        payload = json.loads(rows[0])
    except ValueError as exc:
        raise GateFailure("chatgpt_surface_prepare_failed", "surface_result_invalid") from exc
    if not isinstance(payload, dict):
        raise GateFailure("chatgpt_surface_prepare_failed", "surface_result_invalid")
    return payload


def _run_surface_preflight(*, python: str, private_dir: Path) -> dict[str, Any]:
    args = [
        python,
        str(REPO_ROOT / "tools" / "chatgpt_surface_preflight.py"),
        "--timeout-sec",
        "12",
    ]
    result = core._run(args, cwd=REPO_ROOT, timeout_sec=45)
    core._write_private(private_dir / "surface-normalize.log", result.stdout)
    payload = _parse_surface_preflight(result.stdout)

    sanitized = {
        "ok": bool(payload.get("ok")),
        "failure_class": str(payload.get("failure_class") or ""),
        "target_count": int(payload.get("target_count", 0) or 0),
        "surface_kind": str(payload.get("surface_kind") or "unknown"),
        "pathname_class": str(payload.get("pathname_class") or "other"),
        "composer_empty": bool(payload.get("composer_empty")),
        "blocking_reason": str(payload.get("blocking_reason") or ""),
        "actions": [
            str(value)
            for value in list(payload.get("actions") or [])
            if str(value) in {"switch_to_chat", "new_chat"}
        ],
    }
    core._write_private(
        private_dir / "surface-preflight.json",
        json.dumps(sanitized, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )

    if result.returncode != 0 or payload.get("ok") is not True:
        failure = str(payload.get("failure_class") or "chatgpt_surface_prepare_failed")
        raise GateFailure(failure, str(payload.get("blocking_reason") or "surface_not_ready"))
    return sanitized


def _passive_surface_recheck(private_dir: Path) -> dict[str, Any]:
    payload = core._health_ready(require_clean=True)
    web = payload.get("chatgpt_web") if isinstance(payload.get("chatgpt_web"), dict) else {}
    surface = web.get("surface") if isinstance(web.get("surface"), dict) else {}
    sanitized = {
        "surface_kind": str(surface.get("surface_kind") or "unknown"),
        "surface_ready": bool(surface.get("surface_ready")),
        "pathname_class": str(surface.get("pathname_class") or "other"),
        "composer_empty": bool(surface.get("composer_empty")),
        "blocking_reason": str(surface.get("blocking_reason") or "surface_probe_failed"),
    }
    core._write_private(
        private_dir / "surface-verify.json",
        json.dumps(sanitized, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )
    if not (
        sanitized["surface_ready"]
        and sanitized["surface_kind"] == "chat"
        and sanitized["composer_empty"]
        and sanitized["blocking_reason"] == "none"
    ):
        reason = sanitized["blocking_reason"]
        failure = {
            "work_surface": "chatgpt_work_surface",
            "work_quota_exhausted": "chatgpt_work_quota_exhausted",
            "usage_exhausted": "chatgpt_usage_exhausted",
            "rate_limited": "chatgpt_web_rate_limited",
            "auth_required": "chatgpt_auth_required",
            "challenge": "chatgpt_challenge",
            "composer_not_empty": "chatgpt_composer_not_empty",
            "target_missing": "chatgpt_target_missing",
            "target_ambiguous": "chatgpt_target_ambiguous",
        }.get(reason, "chatgpt_surface_unknown")
        raise GateFailure(failure, reason)
    return sanitized


def _external_surface_failure_after_core_failure(private_dir: Path) -> GateFailure | None:
    """Return a stable external blocker if the browser entered one during live S3.

    The initial surface preflight can be clean while the long compaction probe later
    encounters account-side rate limiting or quota state. In that case preserve the
    product failure evidence privately, but expose the external surface condition as
    the outer release failure class so operators do not repeatedly rerun the full
    stress probe while the account is still blocked.
    """

    try:
        _passive_surface_recheck(private_dir)
    except GateFailure as exc:
        if exc.gate in _EXTERNAL_SURFACE_FAILURES:
            return exc
    return None


def _promote_core_result(*, outer_private_dir: Path, candidate_commit: str, core_rc: int) -> None:
    result_paths = sorted(
        outer_private_dir.glob("*/result.txt"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not result_paths:
        raise GateFailure("private_result", "core_result_missing")
    text = result_paths[0].read_text(encoding="utf-8")
    if "candidate_commit=" not in text:
        text = text.rstrip() + f"\ncandidate_commit={candidate_commit}\n"
    core._write_private(outer_private_dir / "result.txt", text)
    if core_rc == 0 and "STANDALONE_S3=PASS_LIVE_CLOSED" not in text:
        raise GateFailure("private_result", "core_pass_marker_missing")


def run(
    *,
    acceptance_root: Path,
    private_root: Path,
    turn_timeout_sec: int,
    compaction_timeout_sec: int,
) -> int:
    outer_private_dir = core._private_dir(private_root)
    candidate = ""
    desktop_was_running = False
    try:
        core._preflight_repo()
        candidate = _candidate_commit()
        _emit("S3_PHASE=RELEASE_PREFLIGHT_PASS")

        core._configure_uwa_route()
        core._start_standalone_listener()
        core._health_ready(require_clean=True)
        python = core._validation_python()

        desktop_was_running = _quiet_codex_desktop()
        core._wait_request_cleanup()
        _reset_acceptance_chatgpt_target()
        _emit("S3_PHASE=ACCEPTANCE_TARGET_RESET")

        _run_surface_preflight(
            python=python,
            private_dir=outer_private_dir,
        )

        # The listener may still retain a pool reference to the disposed target.
        # Restart once after normalization, then require a passive re-check.
        core._restart_standalone_listener()
        core._health_ready(require_clean=True)
        _passive_surface_recheck(outer_private_dir)
        _emit("S3_PHASE=BROWSER_SURFACE_PREFLIGHT_PASS")
        _emit("S3_CHATGPT_SURFACE_PREFLIGHT=PASS")

        core_rc = core.run(
            acceptance_root=acceptance_root,
            private_root=outer_private_dir,
            turn_timeout_sec=turn_timeout_sec,
            compaction_timeout_sec=compaction_timeout_sec,
        )
        if core_rc != 0:
            external_failure = _external_surface_failure_after_core_failure(
                outer_private_dir
            )
            if external_failure is not None:
                raise external_failure
        _promote_core_result(
            outer_private_dir=outer_private_dir,
            candidate_commit=candidate,
            core_rc=core_rc,
        )
        return core_rc
    except GateFailure as exc:
        core._write_private(
            outer_private_dir / "result.txt",
            "STANDALONE_S3=FAIL\n"
            f"FAILURE_CLASS={exc.gate}\n"
            f"DETAIL={exc.detail}\n"
            + (f"candidate_commit={candidate}\n" if candidate else ""),
        )
        _emit("STANDALONE_S3=FAIL")
        _emit(f"FAILURE_CLASS={exc.gate}")
        if exc.detail:
            _emit(f"FAILURE_DETAIL={exc.detail}")
        _emit("PRIVATE_EVIDENCE_RECORDED=YES")
        return 1
    except Exception as exc:
        core._write_private(
            outer_private_dir / "result.txt",
            "STANDALONE_S3=FAIL\n"
            "FAILURE_CLASS=unexpected_exception\n"
            f"DETAIL={exc.__class__.__name__}\n"
            + (f"candidate_commit={candidate}\n" if candidate else ""),
        )
        _emit("STANDALONE_S3=FAIL")
        _emit("FAILURE_CLASS=unexpected_exception")
        _emit(f"FAILURE_DETAIL={exc.__class__.__name__}")
        _emit("PRIVATE_EVIDENCE_RECORDED=YES")
        return 1
    finally:
        _restore_codex_desktop(desktop_was_running)


def main() -> int:
    import argparse

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--acceptance-root",
        type=Path,
        default=core.DEFAULT_ACCEPTANCE_ROOT,
    )
    parser.add_argument(
        "--private-root",
        type=Path,
        default=core.DEFAULT_PRIVATE_ROOT,
    )
    parser.add_argument(
        "--turn-timeout-sec",
        type=int,
        default=core.DEFAULT_TURN_TIMEOUT_SEC,
    )
    parser.add_argument(
        "--compaction-timeout-sec",
        type=int,
        default=core.DEFAULT_COMPACTION_TIMEOUT_SEC,
    )
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
