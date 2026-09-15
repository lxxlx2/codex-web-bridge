import json
from pathlib import Path

from tools import codex_remote_compaction_recovery_staged as staged


def test_staged_prompts_keep_token_conversation_only_and_require_one_tool_each():
    prompts = [
        staged.build_guard_prompt(),
        staged.build_write_prompt(),
        staged.build_read_prompt(),
    ]

    for prompt in prompts:
        assert staged.base.TOKEN not in prompt
        assert "exec_command" in prompt
        assert "~/.codex" in prompt
        assert "~/.uwa" in prompt

    assert staged.GUARD_REPLY in prompts[0]
    assert staged.WRITE_REPLY in prompts[1]
    assert staged.READ_REPLY in prompts[2]


def test_stage_semantic_contracts_are_disjoint():
    result_rel = staged.base.RESULT_RELATIVE.as_posix()
    guard = staged.legacy._command_semantics(
        f"pwd && test -f {staged.base.MARKER} && test -d {staged.base.SCENARIO}"
    )
    write = staged.legacy._command_semantics(
        f"printf '%s\\n' '{staged.base.TOKEN}' > {result_rel}"
    )
    read = staged.legacy._command_semantics(f"cat {result_rel}")

    assert staged._guard_semantics(guard) is True
    assert staged._write_semantics(write) is True
    assert staged._read_semantics(read) is True

    assert staged._guard_semantics(write) is False
    assert staged._guard_semantics(read) is False
    assert staged._write_semantics(guard) is False
    assert staged._write_semantics(read) is False
    assert staged._read_semantics(guard) is False
    assert staged._read_semantics(write) is False


def test_stage_semantics_reject_private_history_search():
    result_rel = staged.base.RESULT_RELATIVE.as_posix()
    unsafe_write = staged.legacy._command_semantics(
        f"rg token ~/.codex && printf '%s\\n' '{staged.base.TOKEN}' > {result_rel}"
    )
    assert unsafe_write["private_search"] is True
    assert staged._write_semantics(unsafe_write) is False


def test_clean_owned_result_makes_gate_rerunnable(tmp_path: Path):
    result = tmp_path / staged.base.RESULT_RELATIVE
    evidence = tmp_path / staged.EVIDENCE_RELATIVE
    result.parent.mkdir(parents=True)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    result.write_text(staged.base.TOKEN + "\n", encoding="utf-8")
    evidence.write_text("{}\n", encoding="utf-8")

    assert staged._clean_owned_result(tmp_path) is True
    assert not result.exists()
    assert not evidence.exists()
    assert staged._clean_owned_result(tmp_path) is False


def test_trace_readback_exact_requires_exact_token_output(tmp_path: Path):
    trace = tmp_path / "read.jsonl"
    event = {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": f"cat {staged.base.RESULT_RELATIVE.as_posix()}",
            "aggregated_output": staged.base.TOKEN + "\n",
        },
    }
    trace.write_text(json.dumps(event) + "\n", encoding="utf-8")
    assert staged._trace_readback_exact(trace) is True

    event["item"]["aggregated_output"] = staged.base.TOKEN + "\nextra\n"
    trace.write_text(json.dumps(event) + "\n", encoding="utf-8")
    assert staged._trace_readback_exact(trace) is False


def test_trace_readback_exact_fails_without_completed_command(tmp_path: Path):
    trace = tmp_path / "read.jsonl"
    trace.write_text(
        json.dumps({"type": "item.started", "item": {"type": "command_execution"}}) + "\n",
        encoding="utf-8",
    )
    assert staged._trace_readback_exact(trace) is False
