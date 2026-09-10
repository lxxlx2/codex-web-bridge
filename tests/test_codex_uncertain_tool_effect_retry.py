import asyncio
import json

from fastapi.responses import StreamingResponse

from app.api.chat import ResponsesRequest
from app.api import codex_responses_v2 as v2
from app.services.codex_v2_runtime_hardening import install_codex_v2_runtime_hardening


def _tool():
    return {
        "type": "function",
        "name": "exec_command",
        "description": "run local command",
        "parameters": {"type": "object"},
    }


def _body():
    return ResponsesRequest(
        model="chatgpt",
        stream=True,
        input=[{"role": "user", "content": "must use exec_command"}],
        tools=[_tool()],
    )


def _frame(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def _created(response_id: str) -> str:
    return _frame(
        "response.created",
        {
            "type": "response.created",
            "response": {"id": response_id, "status": "in_progress"},
        },
    )


def _completed(response_id: str) -> str:
    return _frame(
        "response.completed",
        {
            "type": "response.completed",
            "response": {"id": response_id, "status": "completed"},
        },
    )


def _failed(response_id: str) -> str:
    return _frame(
        "response.failed",
        {
            "type": "response.failed",
            "response": {"id": response_id, "status": "failed"},
        },
    )


def _call(call_id: str = "call_safe") -> str:
    return _frame(
        "response.output_item.done",
        {
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "call_id": call_id,
                "name": "exec_command",
                "arguments": '{"cmd":"pwd"}',
            },
        },
    )


def _response(chunks):
    async def iterator():
        for chunk in chunks:
            yield chunk

    return StreamingResponse(iterator(), media_type="text/event-stream")


def _summary(chunks):
    text = "".join(chunks)
    names = ["exec_command"] if '"type": "function_call"' in text else []
    if '"status": "failed"' in text:
        status = "failed"
    elif '"status": "completed"' in text:
        status = "completed"
    else:
        status = "in_progress"
    return {
        "function_call_names": names,
        "response_status": status,
    }


def _collect(generator):
    async def run():
        return [chunk async for chunk in generator]

    return asyncio.run(run())


def _install_and_patch_common(monkeypatch):
    install_codex_v2_runtime_hardening()
    monkeypatch.setattr(v2, "_strict_retry_max", lambda: 1)
    monkeypatch.setattr(v2, "summarize_responses_sse", _summary)
    monkeypatch.setattr(v2, "write_trace_attempt", lambda **kwargs: None)


def test_observed_client_function_call_stops_automatic_strict_retry(monkeypatch):
    _install_and_patch_common(monkeypatch)
    attempts = []

    async def fake_attempt(**kwargs):
        attempts.append(kwargs["body"])
        return _response([
            ": keepalive\n\n",
            _created("resp_call"),
            _call("call_effect_possible"),
            _completed("resp_call"),
        ])

    monkeypatch.setattr(v2, "_codex_web_attempt_response", fake_attempt)

    output = _collect(
        v2._strict_required_tool_stream(
            request=object(),
            body=_body(),
            authenticated=True,
            required_tool="exec_command",
            trace_id="trace-test",
        )
    )
    joined = "".join(output)

    assert len(attempts) == 1
    assert "call_effect_possible" in joined
    assert "codex-v2-required-tool-retry" not in joined


def test_terminal_failure_stops_automatic_strict_retry(monkeypatch):
    _install_and_patch_common(monkeypatch)
    attempts = []

    async def fake_attempt(**kwargs):
        attempts.append(kwargs["body"])
        return _response([
            _created("resp_failed"),
            _failed("resp_failed"),
        ])

    monkeypatch.setattr(v2, "_codex_web_attempt_response", fake_attempt)

    output = _collect(
        v2._strict_required_tool_stream(
            request=object(),
            body=_body(),
            authenticated=True,
            required_tool="exec_command",
            trace_id="trace-test",
        )
    )
    joined = "".join(output)

    assert len(attempts) == 1
    assert "response.failed" in joined
    assert "codex-v2-required-tool-retry" not in joined


def test_no_tool_attempt_may_retry_before_any_client_effect_is_delivered(monkeypatch):
    _install_and_patch_common(monkeypatch)
    attempts = []

    async def fake_attempt(**kwargs):
        attempts.append(kwargs["body"])
        if len(attempts) == 1:
            return _response([
                ": keepalive\n\n",
                _created("resp_buffered_no_tool"),
                _completed("resp_buffered_no_tool"),
            ])
        return _response([
            _created("resp_repair_tool"),
            _call("call_repair"),
            _completed("resp_repair_tool"),
        ])

    monkeypatch.setattr(v2, "_codex_web_attempt_response", fake_attempt)

    output = _collect(
        v2._strict_required_tool_stream(
            request=object(),
            body=_body(),
            authenticated=True,
            required_tool="exec_command",
            trace_id="trace-test",
        )
    )
    joined = "".join(output)

    assert len(attempts) == 2
    assert "codex-v2-required-tool-retry attempt=2" in joined
    assert "resp_buffered_no_tool" not in joined
    assert "resp_repair_tool" in joined
    assert "call_repair" in joined
