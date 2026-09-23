import json

from app.api.chat import ChatRequest, ResponsesRequest, _responses_request_to_chat_request
from app.api.codex_responses_v2 import (
    _browser_delta_chat_request,
    _browser_history_suffix_chat_request,
    _clone_for_required_tool_retry,
    _completed_response_has_no_output,
    _required_tool_failed_events,
    required_declared_tool,
)
from app.services.client_tool_policy import (
    looks_like_acceptance_completion_without_exact_sentinel,
    looks_like_incomplete_acceptance_continuation,
    looks_like_premature_acceptance_success,
)
from app.services.tool_calling_prompts import build_browser_messages_for_tools


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


def test_retry_preserves_compound_user_command_semantics():
    command = (
        "pwd && test -f .uwa_codex_acceptance "
        "&& test -d large_context"
    )

    body = _body(
        "必须通过客户端 exec_command 在当前工作区执行 "
        + command
        + "。不得拆分。"
    )

    retry = _clone_for_required_tool_retry(
        body,
        "exec_command",
        attempt=2,
        previous_response_id="resp_compound",
    )

    repair_text = retry.input[0]["content"]

    assert command in repair_text
    assert (
        "Do not weaken, shorten, split, substitute"
        in repair_text
    )
    assert (
        "partial probe such as `pwd` alone"
        in repair_text
    )
    assert (
        "<original_user_request>"
        in repair_text
    )


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


def test_completed_empty_output_is_rejected():
    assert _completed_response_has_no_output(
        "completed",
        {"output": []},
    )
    assert _completed_response_has_no_output(
        "completed",
        {"output": None},
    )
    assert not _completed_response_has_no_output(
        "completed",
        {"output": [{"type": "message"}]},
    )
    assert not _completed_response_has_no_output(
        "incomplete",
        {"output": []},
    )

def test_affinity_structured_tool_delta_carries_private_compacted_context():
    compacted = (
        "[Compacted prior context]\n"
        "[ACTIVE CONTINUATION STATE]\n"
        "Continue large_context/result.txt and only then return LARGE_CONTEXT_PASS."
    )
    state = ChatRequest(
        model="chatgpt",
        messages=[
            {"role": "assistant", "content": compacted},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_latest",
                        "type": "function",
                        "function": {
                            "name": "exec_command",
                            "arguments": '{"cmd":"pwd && ls -la large_context"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_latest",
                "name": "exec_command",
                "content": "Process exited with code 0\nFinal output: total 0\n",
            },
        ],
        tools=[],
    )
    source = ResponsesRequest(
        model="chatgpt",
        input=[
            {
                "type": "function_call_output",
                "call_id": "call_latest",
                "output": "Process exited with code 0\nFinal output: total 0\n",
            }
        ],
        tools=[_tool("exec_command")],
    )

    delta = _browser_delta_chat_request(state, source)
    tool_messages = [
        message
        for message in delta.messages
        if isinstance(message, dict)
        and message.get("role") == "tool"
    ]

    assert tool_messages
    assert (
        tool_messages[-1]["_uwa_compacted_continuation_context"]
        == compacted
    )


def _synthetic_restart_response_history(*, include_readback: bool) -> ResponsesRequest:
    """Use Responses items shaped like a restart turn, with synthetic values only."""

    items = [
        {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        "Use exec_command to run pwd && test -f .uwa_codex_acceptance "
                        "&& test -d context. After that succeeds, write "
                        "context/result.txt, perform a separate byte readback, and "
                        "only then reply CONTEXT_PASS."
                    ),
                }
            ],
        },
        {
            "type": "function_call",
            "call_id": "call_synthetic_validate",
            "name": "exec_command",
            "arguments": json.dumps(
                {"cmd": "pwd && test -f .uwa_codex_acceptance && test -d context"}
            ),
        },
        {
            "type": "function_call_output",
            "call_id": "call_synthetic_validate",
            "output": "Process exited with code 0\nFinal output: /synthetic\n",
        },
        {
            "type": "function_call",
            "call_id": "call_synthetic_write",
            "name": "exec_command",
            "arguments": json.dumps(
                {"cmd": "printf '%s\\n' 'SYNTHETIC-7319' > context/result.txt"}
            ),
        },
        {
            "type": "function_call_output",
            "call_id": "call_synthetic_write",
            "output": "Process exited with code 0\nFinal output:\n",
        },
    ]
    if include_readback:
        items.extend(
            [
                {
                    "type": "function_call",
                    "call_id": "call_synthetic_read",
                    "name": "exec_command",
                    "arguments": json.dumps(
                        {"cmd": "od -An -tx1 -v context/result.txt"}
                    ),
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_synthetic_read",
                    "output": (
                        "Process exited with code 0\n"
                        "Final output: 53 59 4e 54 48 45 54 49 43 2d 37 33 31 39 0a\n"
                    ),
                },
            ]
        )
    return ResponsesRequest(model="chatgpt", input=items, tools=[_tool("exec_command")])


def test_affinity_restart_delta_retains_proven_write_and_pending_byte_readback():
    full = _synthetic_restart_response_history(include_readback=False)
    state = _responses_request_to_chat_request(full, stream=False)
    assert looks_like_incomplete_acceptance_continuation(
        "ACCEPTANCE_INCOMPLETE", state.messages
    )
    source = ResponsesRequest(
        model="chatgpt",
        previous_response_id="resp_synthetic_prior",
        input=[full.input[-1]],
        tools=[_tool("exec_command")],
    )

    delta = _browser_delta_chat_request(state, source)

    # The web conversation already has the earlier history. Keep its visible
    # delta short while retaining trusted history for local policy decisions.
    assert [message["role"] for message in delta.messages] == ["assistant", "tool"]
    assert looks_like_incomplete_acceptance_continuation(
        "ACCEPTANCE_INCOMPLETE", delta.messages
    )
    assert looks_like_premature_acceptance_success("CONTEXT_PASS", delta.messages)
    browser_messages = build_browser_messages_for_tools(
        messages=delta.messages,
        tools=[_tool("exec_command")],
        tool_choice="auto",
    )
    assert "_uwa_synthetic_acceptance_state" not in json.dumps(browser_messages)


def test_affinity_restart_delta_recognizes_completed_byte_readback():
    full = _synthetic_restart_response_history(include_readback=True)
    state = _responses_request_to_chat_request(full, stream=False)
    assert looks_like_acceptance_completion_without_exact_sentinel(
        "The file is verified.", state.messages
    )
    source = ResponsesRequest(
        model="chatgpt",
        previous_response_id="resp_synthetic_prior",
        input=[full.input[-1]],
        tools=[_tool("exec_command")],
    )

    delta = _browser_delta_chat_request(state, source)

    assert [message["role"] for message in delta.messages] == ["assistant", "tool"]
    assert not looks_like_premature_acceptance_success(
        "CONTEXT_PASS", delta.messages
    )
    assert looks_like_acceptance_completion_without_exact_sentinel(
        "The file is verified.", delta.messages
    )


def test_full_history_affinity_suffix_retains_pending_byte_readback():
    full = _synthetic_restart_response_history(include_readback=False)
    state = _responses_request_to_chat_request(full, stream=False)

    # A full-history 0.156 continuation can reuse an affined Web conversation
    # by sending only the unmatched suffix after the validation pair.
    suffix = _browser_history_suffix_chat_request(state, 3)

    assert [message["role"] for message in suffix.messages] == ["assistant", "tool"]
    assert looks_like_incomplete_acceptance_continuation(
        "ACCEPTANCE_INCOMPLETE", suffix.messages
    )
    assert looks_like_premature_acceptance_success("CONTEXT_PASS", suffix.messages)
