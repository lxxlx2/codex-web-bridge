from app.api.chat import ResponsesRequest
from app.api import codex_responses_v2 as v2
from app.services.codex_required_tool_language_patch import (
    install_codex_required_tool_language_patch,
)
from app.services.codex_v2_runtime_hardening import (
    _completed_function_call_names,
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
