import json
import sys
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import codex_auto_compact_trigger_probe as probe  # noqa: E402
import codex_large_context_acceptance as base  # noqa: E402


def test_thresholds_match_codex_01534_model_semantics():
    assert probe.auto_compact_limit(64_000) == 57_600
    assert probe.hard_context_limit(64_000) == 60_800


def test_active_response_tokens_are_delta_of_cli_cumulative_usage():
    assert probe.active_response_tokens(7_213, 21_343) == 14_130
    assert probe.active_response_tokens(21_343, 42_390) == 21_047


def test_trigger_prompt_is_tiny_and_does_not_leak_memory_token():
    prompt = probe.build_trigger_prompt()
    assert base.TOKEN not in prompt
    assert probe.TRIGGER_ACK in prompt
    assert "Do not call tools" in prompt
    assert len(prompt.encode("utf-8")) < 1_000


def test_rollout_compact_marker_counter_uses_types_only(tmp_path):
    rollout = tmp_path / "rollout.jsonl"
    records = [
        {"type": "event_msg", "payload": {"type": "token_count", "info": {"secret": "x"}}},
        {"type": "event_msg", "payload": {"type": "context_compacted", "private": "ignored"}},
        {"type": "compacted", "payload": {"message": "private summary"}},
        {"type": "event_msg", "payload": {"type": "turn_complete"}},
    ]
    rollout.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    assert probe.count_rollout_compact_markers(rollout) == 2


def test_cumulative_tokens_uses_latest_cli_usage_snapshot():
    observation = base.ExecObservation(
        returncode=0,
        input_tokens=[7_158, 21_230],
        output_tokens=[55, 113],
    )
    assert probe.cumulative_tokens(observation) == 21_343
