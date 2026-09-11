from app.api.chat import ResponsesRequest
from app.api import codex_responses_v2 as v2
from app.services import codex_remote_compaction_v2 as remote
from app.services.codex_required_tool_language_patch import (
    install_codex_required_tool_language_patch,
)
from app.services.codex_v2_runtime_hardening import (
    _CALL_RESPONSE_LOCK,
    _CALL_RESPONSE_IDS,
    _CALL_TOOL_NAMES,
    _REQUIRED_TOOL_SATISFIED_KEYS,
    _completed_function_call_names,
    _remember_call_tools,
    _remember_required_tool_satisfaction,
    _required_tool_satisfaction_seen,
    install_codex_v2_runtime_hardening,
)


def _tool(name: str):
    return {
        "type": "function",
        "name": name,
        "description": f"test {name}",
        "parameters": {
            "type": "object",
            "properties": {"cmd": {"type": "string"}},
            "required": ["cmd"],
        },
    }


def _user(text: str):
    return {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": text}],
    }


def _call(name: str, call_id: str):
    return {
        "type": "function_call",
        "name": name,
        "call_id": call_id,
        "arguments": '{"cmd":"pwd"}',
    }


def _output(call_id: str):
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": "ok",
    }


def _body(items, *, tool_choice=None):
    install_codex_required_tool_language_patch()
    install_codex_v2_runtime_hardening()
    return ResponsesRequest(
        model="chatgpt",
        stream=True,
        input=items,
        tools=[_tool("exec_command"), _tool("write_stdin")],
        tool_choice=tool_choice,
    )


def _recovery_text() -> str:
    return (
        "第一步必须单独调用一次客户端 exec_command，只执行 pwd。"
        "第二步必须再单独调用一次 exec_command 写入结果。"
    )


def test_completed_matching_cycle_after_latest_user_satisfies_natural_language_requirement():
    body = _body([
        _user(_recovery_text()),
        _call("exec_command", "call_guard"),
        _output("call_guard"),
    ])

    assert _completed_function_call_names(body.input) == {"exec_command"}
    assert v2.required_declared_tool(body) == ""


def test_unmatched_function_call_does_not_satisfy_requirement():
    body = _body([
        _user(_recovery_text()),
        _call("exec_command", "call_guard"),
    ])

    assert _completed_function_call_names(body.input) == set()
    assert v2.required_declared_tool(body) == "exec_command"


def test_unmatched_function_output_does_not_satisfy_requirement():
    body = _body([
        _user(_recovery_text()),
        _output("call_guard"),
    ])

    assert _completed_function_call_names(body.input) == set()
    assert v2.required_declared_tool(body) == "exec_command"


def test_completed_cycle_before_latest_user_cannot_satisfy_new_user_turn():
    body = _body([
        _user("必须使用 exec_command 执行旧任务。"),
        _call("exec_command", "call_old"),
        _output("call_old"),
        _user(_recovery_text()),
    ])

    assert _completed_function_call_names(body.input) == set()
    assert v2.required_declared_tool(body) == "exec_command"


def test_completed_different_tool_does_not_satisfy_required_exec_command():
    body = _body([
        _user(_recovery_text()),
        _call("write_stdin", "call_other"),
        _output("call_other"),
    ])

    assert _completed_function_call_names(body.input) == {"write_stdin"}
    assert v2.required_declared_tool(body) == "exec_command"


def test_mismatched_call_id_does_not_satisfy_requirement():
    body = _body([
        _user(_recovery_text()),
        _call("exec_command", "call_a"),
        _output("call_b"),
    ])

    assert _completed_function_call_names(body.input) == set()
    assert v2.required_declared_tool(body) == "exec_command"


def _clear_runtime_call_memory():
    with _CALL_RESPONSE_LOCK:
        _CALL_RESPONSE_IDS.clear()
        _CALL_TOOL_NAMES.clear()
        _REQUIRED_TOOL_SATISFIED_KEYS.clear()


def test_remembered_real_exec_call_satisfies_output_only_continuation():
    _clear_runtime_call_memory()
    _remember_call_tools(
        {"call_remembered_exec": "exec_command"}
    )

    body = _body([
        _user(_recovery_text()),
        _output("call_remembered_exec"),
    ])

    assert _completed_function_call_names(body.input) == set()
    assert v2.required_declared_tool(body) == ""


def test_unremembered_output_only_continuation_keeps_requirement():
    _clear_runtime_call_memory()

    body = _body([
        _user(_recovery_text()),
        _output("call_unknown_exec"),
    ])

    assert _completed_function_call_names(body.input) == set()
    assert v2.required_declared_tool(body) == "exec_command"


def test_remembered_different_tool_cannot_satisfy_exec_requirement():
    _clear_runtime_call_memory()
    _remember_call_tools(
        {"call_remembered_other": "write_stdin"}
    )

    body = _body([
        _user(_recovery_text()),
        _output("call_remembered_other"),
    ])

    assert _completed_function_call_names(body.input) == set()
    assert v2.required_declared_tool(body) == "exec_command"


def _compaction(lineage: str, summary: str):
    return {
        "type": "compaction",
        "encrypted_content": remote.encode_compaction_envelope(
            summary,
            lineage=lineage,
        ),
    }


def test_satisfaction_survives_recompaction_in_same_lineage():
    _clear_runtime_call_memory()

    lineage = "1" * 32

    original = _body([
        _compaction(
            lineage,
            "checkpoint one",
        ),
        _user(_recovery_text()),
    ])

    assert (
        v2.required_declared_tool(original)
        == "exec_command"
    )

    assert _remember_required_tool_satisfaction(
        original,
        "exec_command",
    )

    replay = _body([
        _compaction(
            lineage,
            "checkpoint two",
        ),
        _user(_recovery_text()),
    ])

    assert _required_tool_satisfaction_seen(
        replay,
        "exec_command",
    )

    assert (
        v2.required_declared_tool(replay)
        == ""
    )


def test_same_prompt_in_different_compaction_lineage_is_not_satisfied():
    _clear_runtime_call_memory()

    first = _body([
        _compaction(
            "2" * 32,
            "thread one",
        ),
        _user(_recovery_text()),
    ])

    assert _remember_required_tool_satisfaction(
        first,
        "exec_command",
    )

    second = _body([
        _compaction(
            "3" * 32,
            "thread two",
        ),
        _user(_recovery_text()),
    ])

    assert not _required_tool_satisfaction_seen(
        second,
        "exec_command",
    )

    assert (
        v2.required_declared_tool(second)
        == "exec_command"
    )


def test_new_user_turn_in_same_lineage_is_not_pre_satisfied():
    _clear_runtime_call_memory()

    lineage = "4" * 32

    first = _body([
        _compaction(
            lineage,
            "checkpoint",
        ),
        _user(_recovery_text()),
    ])

    assert _remember_required_tool_satisfaction(
        first,
        "exec_command",
    )

    second = _body([
        _compaction(
            lineage,
            "checkpoint next",
        ),
        _user(_recovery_text()),
        _user(_recovery_text()),
    ])

    assert not _required_tool_satisfaction_seen(
        second,
        "exec_command",
    )

    assert (
        v2.required_declared_tool(second)
        == "exec_command"
    )


def test_explicit_tool_choice_remains_authoritative_after_completed_cycle():
    body = _body(
        [
            _user(_recovery_text()),
            _call("exec_command", "call_guard"),
            _output("call_guard"),
        ],
        tool_choice={"type": "function", "name": "exec_command"},
    )

    assert _completed_function_call_names(body.input) == {"exec_command"}
    assert v2.required_declared_tool(body) == "exec_command"
