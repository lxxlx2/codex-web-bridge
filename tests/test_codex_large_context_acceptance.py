import json
from pathlib import Path

from tools.codex_large_context_acceptance import (
    COMPACT_ROUTE_MARKER,
    COMPACT_SUCCESS_MARKER,
    EVIDENCE_RELATIVE,
    RESULT_RELATIVE,
    TOKEN,
    _final_commands_safe,
    _workspace_contains_token,
    build_filler_prompt,
    build_final_prompt,
    build_seed_prompt,
    check,
    parse_exec_jsonl,
    prepare,
    scan_log_delta,
)


def _passing_evidence(**overrides):
    evidence = {
        "schema_version": 1,
        "scenario": "large_context",
        "context_window_reported": 64000,
        "filler_bytes_per_round": 20000,
        "filler_rounds_completed": 8,
        "total_filler_bytes": 160000,
        "seed_reply_exact": True,
        "filler_acks_exact": True,
        "prefinal_tool_effects_zero": True,
        "workspace_token_clean_before_final": True,
        "same_thread_observed": True,
        "compact_route_marker_count": 1,
        "compact_success_marker_count": 1,
        "compact_route_observed": True,
        "compact_success_observed": True,
        "first_compact_round": 8,
        "log_reset_observed": False,
        "turn_input_tokens": [100, 8000, 16000, 24000],
        "turn_output_tokens": [10, 10, 10, 10],
        "final_reply_exact": True,
        "final_tools_used": True,
        "final_commands_safe": True,
        "result_exact": True,
        "private_trace_retained": True,
        "private_trace_path_not_recorded": True,
    }
    evidence.update(overrides)
    return evidence


def test_prompts_keep_token_conversation_only_until_final_tool_write():
    seed = build_seed_prompt()
    filler = build_filler_prompt(1, 4096)
    final = build_final_prompt()

    assert TOKEN in seed
    assert "LARGE_CONTEXT_READY" in seed
    assert TOKEN not in filler
    assert TOKEN not in final
    assert "~/.codex" in final
    assert "~/.uwa" in final
    assert RESULT_RELATIVE.as_posix() in final
    assert "LARGE_CONTEXT_PASS" in final


def test_filler_is_deterministic_large_and_has_exact_ack():
    first = build_filler_prompt(3, 8192)
    second = build_filler_prompt(3, 8192)
    other = build_filler_prompt(4, 8192)

    assert first == second
    assert first != other
    assert len(first.encode("utf-8")) > 8192
    assert first.rstrip().endswith("LARGE_CONTEXT_FILLER_ACK_03 and nothing else.")
    assert TOKEN not in first


def test_parse_exec_jsonl_extracts_thread_usage_agent_and_tool_evidence():
    raw = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 1234,
                        "cached_input_tokens": 0,
                        "output_tokens": 22,
                        "reasoning_output_tokens": 2,
                    },
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "cmd-1",
                        "type": "command_execution",
                        "command": "printf test > large_context/result.txt",
                        "aggregated_output": "",
                        "exit_code": 0,
                        "status": "completed",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "msg-1",
                        "type": "agent_message",
                        "text": "LARGE_CONTEXT_PASS",
                    },
                }
            ),
        ]
    )

    observed = parse_exec_jsonl(raw)

    assert observed.thread_ids == ["thread-1"]
    assert observed.input_tokens == [1234]
    assert observed.output_tokens == [22]
    assert observed.commands == ["printf test > large_context/result.txt"]
    assert observed.final_message == "LARGE_CONTEXT_PASS"
    assert observed.tool_effect_count == 1


def test_scan_log_delta_counts_only_new_compaction_markers(tmp_path: Path):
    log = tmp_path / "uwa.log"
    prefix = "old line\n"
    log.write_text(prefix, encoding="utf-8")
    offset = log.stat().st_size
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"POST {COMPACT_ROUTE_MARKER} HTTP/1.1 200\n")
        handle.write(f"INFO {COMPACT_SUCCESS_MARKER} 1 assistant item(s)\n")

    evidence = scan_log_delta(log, offset)

    assert evidence.route_markers == 1
    assert evidence.success_markers == 1
    assert evidence.log_reset is False
    assert evidence.next_offset == log.stat().st_size


def test_prepare_creates_isolated_large_context_scenario(tmp_path: Path):
    root = tmp_path / "acceptance"
    prepared = prepare(root)

    assert prepared == root.resolve()
    assert (root / ".uwa_codex_acceptance").is_file()
    assert (root / ".git").is_dir()
    assert (root / "large_context").is_dir()
    assert not (root / RESULT_RELATIVE).exists()
    assert not (root / EVIDENCE_RELATIVE).exists()


def test_workspace_token_scan_detects_leak_outside_git(tmp_path: Path):
    root = tmp_path / "acceptance"
    root.mkdir()
    (root / "safe.txt").write_text("safe\n", encoding="utf-8")
    assert _workspace_contains_token(root) == []

    leaked = root / "leak.txt"
    leaked.write_text(TOKEN + "\n", encoding="utf-8")
    assert _workspace_contains_token(root) == ["leak.txt"]


def test_final_command_safety_rejects_session_history_searches():
    assert _final_commands_safe(
        [
            "pwd && test -f .uwa_codex_acceptance && test -d large_context",
            "printf 'value\\n' > large_context/result.txt && cat large_context/result.txt",
        ]
    )
    assert not _final_commands_safe(["rg ORBIT ~/.codex/sessions"])
    assert not _final_commands_safe(["grep -R token ~/.uwa/"])


def test_checker_requires_real_compaction_success_evidence(tmp_path: Path, capsys):
    root = prepare(tmp_path / "acceptance")
    (root / RESULT_RELATIVE).write_text(TOKEN + "\n", encoding="utf-8")
    evidence_path = root / EVIDENCE_RELATIVE
    evidence_path.write_text(
        json.dumps(_passing_evidence(), indent=2) + "\n",
        encoding="utf-8",
    )

    assert check(root) == 0
    output = capsys.readouterr().out
    assert "large_context: PASS" in output
    assert "COMPACTION_EVIDENCE=PASS" in output
    assert "LARGE_CONTEXT_PASS" in output


def test_checker_classifies_recovery_without_compaction_as_unproven(tmp_path: Path, capsys):
    root = prepare(tmp_path / "acceptance")
    (root / RESULT_RELATIVE).write_text(TOKEN + "\n", encoding="utf-8")
    evidence_path = root / EVIDENCE_RELATIVE
    evidence_path.write_text(
        json.dumps(
            _passing_evidence(
                compact_route_marker_count=0,
                compact_success_marker_count=0,
                compact_route_observed=False,
                compact_success_observed=False,
                first_compact_round=None,
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    assert check(root) == 2
    output = capsys.readouterr().out
    assert "STRESS_PASS_COMPACTION_UNPROVEN" in output
