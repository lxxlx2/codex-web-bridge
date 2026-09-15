import sys
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import codex_large_context_live as live  # noqa: E402


def test_failed_turn_private_trace_is_reparsed_instead_of_raising(tmp_path):
    trace = tmp_path / "failed.jsonl"

    def _failing_turn(**kwargs):
        Path(kwargs["trace_path"]).write_text(
            '{"type":"thread.started","thread_id":"synthetic-thread"}\n'
            '{"type":"turn.started"}\n'
            '{"type":"error","message":"idle timeout waiting for SSE"}\n'
            '{"type":"turn.failed","error":{"message":"idle timeout waiting for SSE"}}\n',
            encoding="utf-8",
        )
        raise RuntimeError("synthetic failed turn")

    observation = live.run_turn_preserving_failure_evidence(
        _failing_turn,
        trace_path=trace,
    )

    assert observation.returncode != 0
    assert observation.thread_ids == ["synthetic-thread"]
    assert observation.final_message == ""
    assert observation.tool_effect_count == 0


def test_successful_turn_is_returned_unchanged():
    sentinel = object()

    def _success(**_kwargs):
        return sentinel

    assert live.run_turn_preserving_failure_evidence(_success, trace_path="unused") is sentinel
