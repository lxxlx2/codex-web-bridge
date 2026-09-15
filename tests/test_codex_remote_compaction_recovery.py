import json
from pathlib import Path

from tools import codex_remote_compaction_recovery as recovery


def test_recovery_prompt_keeps_token_conversation_only():
    prompt = recovery.build_recovery_prompt()
    assert recovery.base.TOKEN not in prompt
    assert recovery.RECOVERY_REPLY in prompt
    assert "~/.codex" in prompt
    assert "~/.uwa" in prompt
    assert recovery.base.RESULT_RELATIVE.as_posix() in prompt


def test_command_contract_requires_guard_write_reference_and_readback():
    commands = [
        f"pwd && test -f {recovery.base.MARKER} && test -d {recovery.base.SCENARIO}",
        f"printf '%s\\n' '<remembered-token>' > {recovery.base.RESULT_RELATIVE.as_posix()}",
        f"cat {recovery.base.RESULT_RELATIVE.as_posix()}",
    ]
    result = recovery._command_contract(commands)
    assert all(result.values())


def test_command_contract_rejects_private_history_search():
    commands = [
        f"pwd && test -f {recovery.base.MARKER} && test -d {recovery.base.SCENARIO}",
        "rg ORBIT ~/.codex",
        f"cat {recovery.base.RESULT_RELATIVE.as_posix()}",
    ]
    result = recovery._command_contract(commands)
    assert result["safe"] is False


def test_guard_trace_dir_rejects_non_private_root(tmp_path: Path):
    outside = tmp_path / "trace"
    outside.mkdir()
    try:
        recovery._guard_trace_dir(outside)
    except ValueError as exc:
        assert "private P1.2 trace root" in str(exc)
    else:
        raise AssertionError("outside trace dir should be rejected")


def test_recover_thread_id_requires_one_unique_thread(tmp_path: Path):
    trace = tmp_path
    (trace / "trigger-probe-seed.jsonl").write_text(
        '{"type":"thread.started","thread_id":"thread-one"}\n',
        encoding="utf-8",
    )
    (trace / "trigger-probe-final-trigger.jsonl").write_text(
        '{"type":"thread.started","thread_id":"thread-one"}\n',
        encoding="utf-8",
    )
    assert recovery._recover_thread_id(trace) == "thread-one"

    (trace / "trigger-probe-extra.jsonl").write_text(
        '{"type":"thread.started","thread_id":"thread-two"}\n',
        encoding="utf-8",
    )
    assert recovery._recover_thread_id(trace) is None


def test_private_trace_text_decodes_timeout_bytes_literal(tmp_path: Path):
    payload = (
        '{"type":"thread.started","thread_id":"thread-one"}\n'
        '{"type":"turn.completed","usage":{"input_tokens":12,"output_tokens":3}}\n'
    )
    trace = tmp_path / "timeout.jsonl"
    trace.write_text(repr(payload.encode("utf-8")) + "\nTIMEOUT\n", encoding="utf-8")

    decoded = recovery._private_trace_text(trace)
    observation = recovery.base.parse_exec_jsonl(decoded, 0)

    assert decoded == payload
    assert observation.thread_ids == ["thread-one"]
    assert observation.input_tokens == [12]
    assert observation.output_tokens == [3]


def test_partial_timeout_summary_classifies_recovery_stage_without_raw_bodies(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    result_path = root / recovery.base.RESULT_RELATIVE
    result_path.parent.mkdir(parents=True)
    result_path.write_text(recovery.base.TOKEN + "\n", encoding="utf-8")

    guard = f"pwd && test -f {recovery.base.MARKER} && test -d {recovery.base.SCENARIO}"
    write = (
        f"printf '%s\\n' '<remembered-token>' > "
        f"{recovery.base.RESULT_RELATIVE.as_posix()}"
    )
    read = f"cat {recovery.base.RESULT_RELATIVE.as_posix()}"
    events = [
        {"type": "thread.started", "thread_id": "thread-one"},
        {
            "type": "item.completed",
            "item": {"type": "command_execution", "command": guard},
        },
        {
            "type": "item.completed",
            "item": {"type": "command_execution", "command": write},
        },
        {
            "type": "item.completed",
            "item": {"type": "command_execution", "command": read},
        },
        {"type": "error", "message": "skill budget warning"},
    ]
    payload = "".join(json.dumps(event) + "\n" for event in events)
    trace = tmp_path / "post-remote-recovery.jsonl"
    trace.write_text(payload, encoding="utf-8")

    summary = recovery._partial_timeout_summary(trace, "thread-one", root)

    assert summary["trace_exists"] is True
    assert summary["same_thread"] == "YES"
    assert summary["completed_command_count"] == 3
    assert summary["commands"][0]["is_workspace_guard"] is True
    assert summary["commands"][1]["refs_result_path"] is True
    assert summary["commands"][1]["write_like"] is True
    assert summary["commands"][2]["read_like"] is True
    assert summary["errors"]["count"] == 1
    assert summary["errors"]["skill_budget_warning"] is True
    assert summary["errors"]["http_403"] is False
    assert summary["result_exists"] is True
    assert summary["result_exact"] is True


def test_command_semantics_does_not_expose_command_body():
    command = f"cat {recovery.base.RESULT_RELATIVE.as_posix()}"
    semantics = recovery._command_semantics(command)

    assert semantics["refs_result_path"] is True
    assert semantics["read_like"] is True
    assert semantics["contains_conversation_token"] is False
    assert semantics["private_search"] is False
    assert "command" not in semantics
    assert set(semantics) == {
        "is_workspace_guard",
        "refs_result_path",
        "contains_conversation_token",
        "write_like",
        "read_like",
        "private_search",
        "sha256",
        "length",
    }
