#!/usr/bin/env python3
"""Release-grade office-work soak for Codex Web Bridge.

This gate complements the synthetic S3 compaction stress test with a small set
of safe, reversible office-like tasks in the isolated acceptance workspace.

The soak deliberately does not add a fallback provider. If ChatGPT Web, the
browser surface, the bridge, or a Codex client-tool turn fails, the run stops and
records a bounded failure. It never retries a failed side-effecting task.

Coverage:
- same-thread context recall plus byte-exact file verification;
- multi-file implementation edits with tests and diff-scope verification;
- observe-real-failure -> fix -> rerun workflow;
- requirements-driven config edit plus git-diff discipline;
- long-running process plus write_stdin continuation;
- UWA/chatgpt/high route evidence;
- request-manager cleanup and release-repository cleanliness.

Raw Codex JSONL stays under ~/.uwa/standalone-office-soak.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Callable

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import codex_desktop_acceptance as desktop
import codex_route_audit as route_audit
import standalone_s3_live_acceptance as s3
import standalone_s3_live_core as core


DEFAULT_ACCEPTANCE_ROOT = Path.home() / "uwa-codex-acceptance"
DEFAULT_PRIVATE_ROOT = Path.home() / ".uwa" / "standalone-office-soak"
DEFAULT_TURN_TIMEOUT_SEC = 600
DEFAULT_TURN_GAP_SEC = 60
SCENARIOS = (
    "multi_file",
    "failure_recovery",
    "git_diff",
    "interactive",
)


class GateFailure(RuntimeError):
    def __init__(self, gate: str, detail: str = "") -> None:
        super().__init__(detail or gate)
        self.gate = gate
        self.detail = detail


class _silence_stdout:
    def __enter__(self):
        self._buffer = io.StringIO()
        self._redirect = contextlib.redirect_stdout(self._buffer)
        return self._redirect.__enter__()

    def __exit__(self, exc_type, exc, tb):
        return self._redirect.__exit__(exc_type, exc, tb)


def _candidate_commit() -> str:
    result = core._git("rev-parse", "HEAD")
    if result.returncode != 0 or not result.stdout.strip():
        raise GateFailure("git_head", "unable_to_resolve_candidate_commit")
    return result.stdout.strip()


def _turn_gap_seconds() -> int:
    raw = str(os.getenv("UWA_OFFICE_SOAK_TURN_GAP_SEC", DEFAULT_TURN_GAP_SEC)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_TURN_GAP_SEC
    return max(0, min(value, 120))


def _prepare(root: Path, scenario: str) -> None:
    with _silence_stdout():
        desktop.prepare(root, scenario)
        if desktop.preflight(root, scenario) != 0:
            raise GateFailure("office_soak_preflight", f"scenario={scenario}")


def _check(root: Path, scenario: str) -> None:
    with _silence_stdout():
        if desktop.check(root, scenario) != 0:
            raise GateFailure("office_soak_effect_verification", f"scenario={scenario}")


def _pace(last_finished_at: float | None) -> None:
    if last_finished_at is None:
        return
    remaining = _turn_gap_seconds() - (time.monotonic() - last_finished_at)
    if remaining <= 0:
        return
    print(f"OFFICE_SOAK_INTER_TURN_COOLDOWN_SEC={remaining:.1f}", flush=True)
    time.sleep(remaining)


def _run_turn(
    *,
    codex: str,
    root: Path,
    prompt: str,
    trace_path: Path,
    thread_id: str | None,
    timeout_sec: int,
    require_tool_effect: bool,
):
    obs = core._run_codex_turn(
        codex=codex,
        cwd=root,
        prompt=prompt,
        trace_path=trace_path,
        thread_id=thread_id,
        timeout_sec=timeout_sec,
    )
    if obs.returncode != 0:
        raise GateFailure("office_soak_codex_turn", f"rc={obs.returncode}")
    if require_tool_effect and obs.tool_effect_count < 1:
        raise GateFailure("office_soak_client_tool", "real_client_tool_not_observed")
    return obs


def _write_result(private_dir: Path, *, candidate: str, started_at: float, turn_count: int) -> None:
    core._write_private(
        private_dir / "result.txt",
        "STANDALONE_OFFICE_SOAK=PASS\n"
        "OFFICE_SOAK_CONTEXT=PASS\n"
        "OFFICE_SOAK_MULTI_FILE=PASS\n"
        "OFFICE_SOAK_FAILURE_RECOVERY=PASS\n"
        "OFFICE_SOAK_GIT_DIFF=PASS\n"
        "OFFICE_SOAK_INTERACTIVE=PASS\n"
        "OFFICE_SOAK_EFFECT_VERIFICATION=PASS\n"
        "OFFICE_SOAK_ROUTE_UWA_CHATGPT_HIGH=PASS\n"
        "OFFICE_SOAK_REQUEST_MANAGER_CLEAN=PASS\n"
        "OFFICE_SOAK_REPOSITORY_CLEAN=PASS\n"
        f"OFFICE_SOAK_TURN_COUNT={turn_count}\n"
        f"started_at_unix={started_at:.3f}\n"
        f"finished_at_unix={time.time():.3f}\n"
        f"candidate_commit={candidate}\n",
    )


def _classify_surface_after_turn_failure(private_dir: Path, original: GateFailure) -> GateFailure:
    try:
        s3._passive_surface_recheck(private_dir)
    except core.GateFailure as exc:
        if exc.gate in {
            "chatgpt_web_rate_limited",
            "chatgpt_usage_exhausted",
            "chatgpt_work_quota_exhausted",
            "chatgpt_auth_required",
            "chatgpt_challenge",
        }:
            return GateFailure(exc.gate, exc.detail)
    return original


def run(
    *,
    acceptance_root: Path,
    private_root: Path,
    turn_timeout_sec: int,
) -> int:
    private_dir = core._private_dir(private_root)
    started_at = time.time()
    candidate = ""
    turn_count = 0
    last_finished_at: float | None = None

    try:
        core._preflight_repo()
        candidate = _candidate_commit()
        core._configure_uwa_route()
        core._start_standalone_listener()
        core._health_ready(require_clean=True)
        s3._passive_surface_recheck(private_dir)

        root = acceptance_root.expanduser().resolve()
        marker_epoch = route_audit.write_marker()
        codex = shutil.which("codex") or "codex"

        _prepare(root, "context")
        _pace(last_finished_at)
        seed = _run_turn(
            codex=codex,
            root=root,
            prompt=desktop.PROMPTS["context_1"],
            trace_path=private_dir / "context-seed.jsonl",
            thread_id=None,
            timeout_sec=turn_timeout_sec,
            require_tool_effect=False,
        )
        turn_count += 1
        last_finished_at = time.monotonic()
        if seed.final_message != "CONTEXT_READY" or seed.tool_effect_count != 0:
            raise GateFailure("office_soak_context_seed", "seed_contract_failed")
        thread_id = core._unique_thread_id(seed)

        _pace(last_finished_at)
        resumed = _run_turn(
            codex=codex,
            root=root,
            prompt=desktop.PROMPTS["context_2"],
            trace_path=private_dir / "context-resume.jsonl",
            thread_id=thread_id,
            timeout_sec=turn_timeout_sec,
            require_tool_effect=True,
        )
        turn_count += 1
        last_finished_at = time.monotonic()
        if not core._resume_thread_matches(resumed, thread_id):
            raise GateFailure("office_soak_context", "thread_identity_mismatch")
        if resumed.final_message != "CONTEXT_PASS":
            raise GateFailure("office_soak_context", "final_reply_mismatch")
        _check(root, "context")
        print("OFFICE_SOAK_CONTEXT=PASS", flush=True)

        for scenario in SCENARIOS:
            _prepare(root, scenario)
            _pace(last_finished_at)
            obs = _run_turn(
                codex=codex,
                root=root,
                prompt=desktop.PROMPTS[scenario],
                trace_path=private_dir / f"{scenario}.jsonl",
                thread_id=None,
                timeout_sec=turn_timeout_sec,
                require_tool_effect=True,
            )
            turn_count += 1
            last_finished_at = time.monotonic()
            if not obs.final_message:
                raise GateFailure("office_soak_final_reply", f"scenario={scenario}")
            _check(root, scenario)
            print(f"OFFICE_SOAK_{scenario.upper()}=PASS", flush=True)
            core._wait_request_cleanup()
            core._health_ready(require_clean=True)

        core._route_gate(marker_epoch)
        print("OFFICE_SOAK_ROUTE_UWA_CHATGPT_HIGH=PASS", flush=True)
        core._wait_request_cleanup()
        core._health_ready(require_clean=True)

        status = core._git("status", "--porcelain=v1", "--untracked-files=all")
        if status.returncode != 0 or status.stdout.strip():
            raise GateFailure("office_soak_repo_cleanliness", "repository_changed")

        _write_result(
            private_dir,
            candidate=candidate,
            started_at=started_at,
            turn_count=turn_count,
        )
        print("OFFICE_SOAK_EFFECT_VERIFICATION=PASS", flush=True)
        print("OFFICE_SOAK_REQUEST_MANAGER_CLEAN=PASS", flush=True)
        print("OFFICE_SOAK_REPOSITORY_CLEAN=PASS", flush=True)
        print(f"OFFICE_SOAK_TURN_COUNT={turn_count}", flush=True)
        print("STANDALONE_OFFICE_SOAK=PASS", flush=True)
        print(f"candidate_commit={candidate}", flush=True)
        return 0

    except (GateFailure, core.GateFailure) as exc:
        gate = getattr(exc, "gate", "office_soak")
        detail = getattr(exc, "detail", "") or str(exc)
        failure = GateFailure(gate, detail)
        if gate == "office_soak_codex_turn":
            failure = _classify_surface_after_turn_failure(private_dir, failure)

        core._write_private(
            private_dir / "result.txt",
            "STANDALONE_OFFICE_SOAK=FAIL\n"
            f"FAILURE_CLASS={failure.gate}\n"
            f"FAILURE_DETAIL={failure.detail}\n"
            f"OFFICE_SOAK_TURN_COUNT={turn_count}\n"
            f"started_at_unix={started_at:.3f}\n"
            f"finished_at_unix={time.time():.3f}\n"
            + (f"candidate_commit={candidate}\n" if candidate else ""),
        )
        print("STANDALONE_OFFICE_SOAK=FAIL", flush=True)
        print(f"FAILURE_CLASS={failure.gate}", flush=True)
        if failure.detail:
            print(f"FAILURE_DETAIL={failure.detail}", flush=True)
        print("PRIVATE_EVIDENCE_RECORDED=YES", flush=True)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--acceptance-root",
        type=Path,
        default=DEFAULT_ACCEPTANCE_ROOT,
    )
    parser.add_argument(
        "--private-root",
        type=Path,
        default=DEFAULT_PRIVATE_ROOT,
    )
    parser.add_argument(
        "--turn-timeout-sec",
        type=int,
        default=DEFAULT_TURN_TIMEOUT_SEC,
    )
    args = parser.parse_args()
    return run(
        acceptance_root=args.acceptance_root,
        private_root=args.private_root,
        turn_timeout_sec=max(30, min(args.turn_timeout_sec, 1800)),
    )


if __name__ == "__main__":
    raise SystemExit(main())
