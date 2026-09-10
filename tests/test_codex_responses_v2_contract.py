import json

from app.api.chat import ResponsesRequest
from app.api.codex_responses_v2 import (
    _clone_for_required_tool_retry,
    _required_tool_failed_events,
    required_declared_tool,
)


def _tool(name: str):
    return {
        "type": "function",
        "name": name,
        "description": f"test {name}",
        "parameters": {
            "type": "object",
            "properties": {
                "cmd": {"type": "string"},
            },
            "required": ["cmd"],
        },
    }


def _body(text: str, *, tool_choice=None):
    return ResponsesRequest(
        model="chatgpt",
        stream=True,
        input=[
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            }
        ],
        tools=[_tool("exec_command"), _tool("write_stdin")],
        tool_choice=tool_choice,
    )


def test_required_tool_detects_explicit_chinese_exec_command_request():
    body = _body("必须使用 exec_command 执行 pwd，只返回真实输出。")
    assert required_declared_tool(body) == "exec_command"


def test_required_tool_detects_explicit_english_exec_command_request():
    body = _body("You must use exec_command to run pwd and return the real output.")
    assert required_declared_tool(body) == "exec_command"


def test_required_tool_does_not_force_tool_for_plain_reference():
    body = _body("Explain what exec_command means in this protocol.")
    assert required_declared_tool(body) == ""


def test_specific_tool_choice_is_always_treated_as_required():
    body = _body(
        "Run the requested operation.",
        tool_choice={"type": "function", "name": "exec_command"},
    )
    assert required_declared_tool(body) == "exec_command"


def test_retry_forces_declared_tool_as_incremental_chained_turn_without_mutating_original():
    body = _body("必须使用 exec_command 执行 pwd。")
    body.instructions = "original instructions"
    retry = _clone_for_required_tool_retry(
        body,
        "exec_command",
        attempt=2,
        previous_response_id="resp_attempt_one",
    )

    assert body.tool_choice is None
    assert body.instructions == "original instructions"
    assert body.previous_response_id is None

    assert retry.previous_response_id == "resp_attempt_one"
    assert retry.instructions is None
    assert retry.tool_choice == {"type": "function", "name": "exec_command"}
    assert isinstance(retry.input, list) and len(retry.input) == 1
    repair_text = retry.input[0]["content"]
    assert "exec_command" in repair_text
    assert "Do not simulate command output" in repair_text
    assert "omit `workdir`" in repair_text


def test_required_tool_exhaustion_returns_structured_responses_failure():
    body = _body("必须使用 exec_command 执行 pwd。")
    frames = _required_tool_failed_events(body, "exec_command")
    combined = "".join(frames)

    assert "event: response.created" in combined
    assert "event: response.failed" in combined
    assert "required_client_tool_not_called" in combined
    assert "exec_command" in combined

    failed_data = frames[-1].split("data: ", 1)[1].strip()
    payload = json.loads(failed_data)
    assert payload["type"] == "response.failed"
    assert payload["response"]["status"] == "failed"
