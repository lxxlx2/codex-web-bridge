#!/usr/bin/env python3
"""P1.2 live entry that preserves failed-turn UWA evidence.

The base acceptance runner intentionally writes every Codex JSONL turn to a
private trace before interpreting its return code. Its first live version raises
immediately when ``codex exec`` exits non-zero, which means the outer loop never
scans the UWA log bytes appended by that same failed turn.

This thin entry keeps the base protocol and checker unchanged. It intercepts only
that early RuntimeError, reconstructs the already-written private JSONL as a
failed observation, and lets the base loop perform its normal per-turn log scan
before the ACK/contract check fails. Raw trace content remains private.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import codex_large_context_acceptance as base


_ORIGINAL_RUN_CODEX_TURN = base._run_codex_turn


def _returncode_from_trace(text: str) -> int:
    # Current Codex JSONL exposes semantic failure events but not the CLI process
    # status. The wrapper is reached only after the base function raised because
    # subprocess returncode was non-zero or the subprocess timed out, so a
    # generic non-zero value is sufficient for evidence classification.
    return 1


def run_turn_preserving_failure_evidence(
    original: Callable[..., Any],
    **kwargs: Any,
):
    try:
        return original(**kwargs)
    except RuntimeError:
        trace_path = Path(kwargs["trace_path"])
        text = (
            trace_path.read_text(encoding="utf-8", errors="replace")
            if trace_path.exists()
            else ""
        )
        return base.parse_exec_jsonl(text, _returncode_from_trace(text))


def _live_run_codex_turn(**kwargs: Any):
    return run_turn_preserving_failure_evidence(_ORIGINAL_RUN_CODEX_TURN, **kwargs)


def main() -> int:
    base._run_codex_turn = _live_run_codex_turn
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
