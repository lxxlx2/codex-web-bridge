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
    assert probe.trigger_target_limit(64_000, "total") == 57_600
    assert probe.trigger_target_limit(
        64_000,
        "body_after_prefix",
    ) == 60_800


def test_active_response_tokens_are_delta_of_cli_cumulative_usage():
    assert probe.active_response_tokens(7_213, 21_343) == 14_130
    assert probe.active_response_tokens(21_343, 42_390) == 21_047


def test_trigger_prompt_is_tiny_and_does_not_leak_memory_token():
    prompt = probe.build_trigger_prompt()
    assert base.TOKEN not in prompt
    assert probe.TRIGGER_ACK in prompt
    assert "Do not call tools" in prompt
    assert len(prompt.encode("utf-8")) < 256


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


def test_configured_scope_reads_body_after_prefix(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text(
        'model_auto_compact_token_limit_scope = "body_after_prefix"\n',
        encoding="utf-8",
    )

    assert (
        probe.configured_auto_compact_scope(config)
        == "body_after_prefix"
    )


def test_configured_scope_defaults_to_total(tmp_path: Path):
    missing = tmp_path / "missing.toml"

    assert probe.configured_auto_compact_scope(missing) == "total"


def test_dense_payload_is_deterministic_and_character_compact():
    first = probe._dense_deterministic_payload(7, 20_000)
    second = probe._dense_deterministic_payload(7, 20_000)

    assert first == second
    assert len(first.encode("utf-8")) <= 20_000
    assert len(first.encode("utf-8")) >= 19_990
    assert len(first) < 7_000


def test_dense_filler_stays_small_in_browser_characters():
    prompt = probe.build_dense_filler_prompt(3, 20_000)

    assert base.TOKEN not in prompt
    assert "LARGE_CONTEXT_FILLER_ACK_03" in prompt
    assert len(prompt) < 8_000


def test_dense_filler_changes_between_rounds():
    assert (
        probe._dense_deterministic_payload(1, 20_000)
        != probe._dense_deterministic_payload(2, 20_000)
    )

def test_live_validated_defaults_reduce_web_turn_pressure():
    assert probe.DEFAULT_COARSE_BYTES == 46_000
    assert probe.DEFAULT_FINE_BYTES == 2_048
    assert probe.DEFAULT_ARM_GUARD_TOKENS == 512


def test_arm_prompt_is_tiny_token_safe_and_exact():
    prompt = probe.build_arm_prompt(9)
    expected = probe.arm_expected_reply(9)

    assert base.TOKEN not in prompt
    assert expected in prompt
    assert "Do not call tools" in prompt
    assert len(prompt.encode("utf-8")) < 256


def test_switches_from_fixed_fine_fill_to_tiny_arm_near_boundary():
    assert probe.should_arm_before_next_fine(
        51,
        858,
    )
    assert probe.should_arm_before_next_fine(
        400,
        858,
    )
    # Live S3 reached margin=929 with the previous fine step at 858 and the
    # next fine turn failed before reporting usage. Keep one fine-step plus the
    # fixed guard as headroom so this point switches to tiny arm turns.
    assert probe.should_arm_before_next_fine(
        929,
        858,
    )
    assert probe.should_arm_before_next_fine(
        1_370,
        858,
    )
    assert not probe.should_arm_before_next_fine(
        1_371,
        858,
    )
    assert probe.should_arm_before_next_fine(
        400,
        None,
    )
    assert not probe.should_arm_before_next_fine(
        513,
        None,
    )
    assert not probe.should_arm_before_next_fine(
        0,
        858,
    )

def test_trigger_reply_can_defer_only_after_proven_remote_compaction():
    good = dict(
        trigger_exact=False,
        thread_matches=True,
        tool_effect_count=0,
        compact_delta=1,
        remote_route_delta=1,
        remote_success_delta=1,
        token_leak=False,
    )

    assert probe.can_defer_trigger_reply(**good)

    for key, bad_value in (
        ("thread_matches", False),
        ("tool_effect_count", 1),
        ("compact_delta", 0),
        ("remote_route_delta", 0),
        ("remote_success_delta", 0),
        ("token_leak", True),
    ):
        case = dict(good)
        case[key] = bad_value

        assert not probe.can_defer_trigger_reply(
            **case
        )


def test_exact_trigger_reply_does_not_need_deferred_mode():
    assert not probe.can_defer_trigger_reply(
        trigger_exact=True,
        thread_matches=True,
        tool_effect_count=0,
        compact_delta=1,
        remote_route_delta=1,
        remote_success_delta=1,
        token_leak=False,
    )

def test_transition_target_reduces_live_871_token_margin_before_arm():
    target = probe.transition_target_bytes(
        margin_to_trigger=871,
        previous_fine_step=858,
        fine_bytes=2048,
    )

    assert target is not None
    assert 1300 <= target <= 1550


def test_transition_target_skips_when_only_tiny_arm_headroom_remains():
    assert probe.transition_target_bytes(
        margin_to_trigger=489,
        previous_fine_step=858,
        fine_bytes=2048,
    ) is None


def test_transition_prompt_is_bounded_and_exact():
    prompt = probe.build_transition_prompt(
        9,
        1400,
    )

    assert base.TOKEN not in prompt
    assert "AUTO_COMPACT_TRANSITION_ACK_09" in prompt
    assert len(prompt.encode("utf-8")) < 2200

