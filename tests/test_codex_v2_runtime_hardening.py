import json

from app.api.chat import ResponsesRequest
from app.services import codex_v2_runtime_hardening as hardening
from app.services.codex_v2_runtime_hardening import (
    _compact_failure_body,
    _completed_function_call_names,
    _degraded_reuse_state_body,
    _failure_events,
    _function_call_output_ids,
    _remember_call_response,
    _resolve_call_response,
    _response_and_call_ids_from_sse,
    _tool_result_delta_body,
)


def _body(*, huge_tool_description: str = "run command"):
    return ResponsesRequest(
        model="chatgpt",
        stream=True,
        previous_response_id="resp_previous",
        instructions="large codex instructions",
        input=[{"role": "user", "content": "test"}],
        tools=[
            {
                "type": "function",
                "name": "exec_command",
                "description": huge_tool_description,
                "parameters": {"type": "object"},
            }
        ],
        tool_choice={"type": "function", "name": "exec_command"},
        metadata={"case": "runtime-hardening"},
    )


def test_failure_boundary_emits_complete_responses_terminal_sequence():
    frames = _failure_events(
        _body(),
        code="codex_v2_attempt_stream_failed",
        exc=RuntimeError("private details must not be copied"),
    )

    assert len(frames) == 2
    assert frames[0].startswith("event: response.created\n")
    assert frames[1].startswith("event: response.failed\n")

    created = json.loads(frames[0].split("data: ", 1)[1].strip())
    failed = json.loads(frames[1].split("data: ", 1)[1].strip())

    assert created["response"]["id"] == failed["response"]["id"]
    assert failed["response"]["status"] == "failed"
    assert failed["response"]["error"]["code"] == "codex_v2_attempt_stream_failed"
    assert "private details must not be copied" not in frames[1]


def test_failure_boundary_does_not_echo_huge_tool_schema():
    body = _body(huge_tool_description="x" * 600_000)
    frames = _failure_events(
        body,
        code="codex_v2_turn_prepare_failed",
        exc=RuntimeError("boom"),
    )

    assert sum(len(frame) for frame in frames) < 20_000
    assert "x" * 1000 not in "".join(frames)


def test_compact_failure_body_removes_request_heavy_fields():
    body = _body()
    compact = _compact_failure_body(body)

    assert compact.model == body.model
    assert compact.stream is True
    assert compact.input == ""
    assert compact.instructions is None
    assert compact.previous_response_id is None
    assert compact.tools is None
    assert compact.tool_choice is None
    assert compact.metadata is None


def test_degraded_reuse_state_keeps_retry_delta_and_tools_but_clears_hydration_handle():
    body = _body()
    degraded = _degraded_reuse_state_body(body)

    assert degraded.previous_response_id is None
    assert degraded.instructions is None
    assert degraded.input == body.input
    assert degraded.tools == body.tools
    assert degraded.tool_choice == body.tool_choice
    assert body.previous_response_id == "resp_previous"
    assert body.instructions == "large codex instructions"


def _full_history_tool_result_body():
    return ResponsesRequest(
        model="chatgpt",
        stream=True,
        input=[
            {
                "type": "message",
                "role": "user",
                "content": "必须使用 exec_command 执行 pwd。",
            },
            {
                "type": "function_call",
                "call_id": "call_pwd_123",
                "name": "exec_command",
                "arguments": '{"cmd":"pwd"}',
            },
            {
                "type": "function_call_output",
                "call_id": "call_pwd_123",
                "output": "/Users/jerson/uwa-codex-acceptance",
            },
        ],
        tools=[
            {
                "type": "function",
                "name": "exec_command",
                "description": "run command",
                "parameters": {"type": "object"},
            }
        ],
    )


def test_completed_function_call_is_detected_from_reconstructed_history():
    body = _full_history_tool_result_body()
    assert _completed_function_call_names(body.input) == {"exec_command"}
    assert _function_call_output_ids(body.input) == ["call_pwd_123"]


def test_tool_result_delta_drops_replayed_user_and_function_call_items():
    body = _full_history_tool_result_body()
    delta = _tool_result_delta_body(body)

    assert delta.previous_response_id is None
    assert delta.instructions is None
    assert isinstance(delta.input, list)
    assert len(delta.input) == 1
    assert delta.input[0]["type"] == "function_call_output"
    assert delta.input[0]["call_id"] == "call_pwd_123"
    assert body.input[0]["type"] == "message"


def test_call_id_to_response_mapping_is_process_local_and_recoverable():
    with hardening._CALL_RESPONSE_LOCK:
        hardening._CALL_RESPONSE_IDS.clear()

    _remember_call_response(["call_pwd_123"], "resp_tool_call")
    assert _resolve_call_response(["call_pwd_123"]) == "resp_tool_call"
    assert _resolve_call_response(["missing_call"]) == ""


def test_sse_parser_recovers_response_and_function_call_ids():
    chunks = [
        "event: response.created\n"
        'data: {"type":"response.created","response":{"id":"resp_tool_call"}}\n\n',
        "event: response.output_item.done\n"
        'data: {"type":"response.output_item.done","item":{"type":"function_call","call_id":"call_pwd_123","name":"exec_command","arguments":"{\\"cmd\\":\\"pwd\\"}"}}\n\n',
        "event: response.completed\n"
        'data: {"type":"response.completed","response":{"id":"resp_tool_call","status":"completed"}}\n\n',
    ]

    response_id, call_ids = _response_and_call_ids_from_sse(chunks)
    assert response_id == "resp_tool_call"
    assert call_ids == ["call_pwd_123"]
