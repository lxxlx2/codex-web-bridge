import asyncio
import json
from types import SimpleNamespace

import pytest

from app.api.chat import ResponsesRequest
from app.services import codex_remote_compaction_v2 as remote


def _message(role: str, text: str):
    content_type = "input_text" if role in {"user", "developer", "system"} else "output_text"
    return {
        "type": "message",
        "role": role,
        "content": [{"type": content_type, "text": text}],
    }


def _trigger_body():
    return ResponsesRequest(
        model="chatgpt",
        stream=True,
        input=[
            _message("user", "Earlier request is complete."),
            _message("user", "Continue the current release validation."),
            {"type": "compaction_trigger"},
        ],
        tools=[
            {
                "type": "function",
                "name": "exec_command",
                "description": "test tool",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        tool_choice="auto",
        parallel_tool_calls=True,
        instructions="Keep the current release goal active.",
        reasoning={"effort": "high"},
    )


class _Request:
    async def is_disconnected(self):
        return False


def _blocking_v2(state):
    counter = {"value": 0}

    def new_response_id():
        counter["value"] += 1
        return f"resp_cancel_{counter['value']}"

    def build_response(body, chat_payload, *, response_id, created_at, status, error, **kwargs):
        return {
            "id": response_id,
            "object": "response",
            "created_at": created_at,
            "model": body.model,
            "status": status,
            "output": [],
            "usage": chat_payload.get("usage", {}),
            "error": error,
        }

    def event(name, *, sequence_number, **fields):
        payload = {"type": name, "sequence_number": sequence_number, **fields}
        return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def to_chat(body, stream=False):
        return SimpleNamespace(
            messages=body.input,
            tools=body.tools,
            tool_choice=body.tool_choice,
        )

    async def run_chat_completion_final(**kwargs):
        state["worker_task"] = asyncio.current_task()
        state["started"].set()
        try:
            await state["release"].wait()
        except asyncio.CancelledError:
            state["cancelled"].set()
            raise
        return (
            200,
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Continue only the current release validation.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {},
            },
        )

    return SimpleNamespace(
        _new_response_id=new_response_id,
        _build_responses_object=build_response,
        _codex_event=event,
        _responses_request_to_chat_request=to_chat,
        _run_chat_completion_final=run_chat_completion_final,
        _CODEX_SSE_KEEPALIVE_SEC=0.01,
        prepare_and_verify_codex_web_mode=lambda reasoning: {"verified": True},
        install_codex_chatgpt_network_tuning=lambda: None,
    )


def _state():
    return {
        "started": asyncio.Event(),
        "release": asyncio.Event(),
        "cancelled": asyncio.Event(),
        "worker_task": None,
    }


def test_compaction_instructions_keep_completed_history_non_actionable():
    backing = remote.build_compaction_backing_body(_trigger_body())
    instructions = str(backing.instructions or "").lower()

    assert "completed historical requests" in instructions
    assert "current active goal" in instructions
    assert "never present a completed old user request as a current actionable instruction" in instructions
    assert "unresolved work" in instructions


def test_consumer_cancellation_cleans_remote_compaction_worker_and_propagates():
    async def scenario():
        state = _state()
        fake = _blocking_v2(state)
        stream = remote._stream_remote_compaction_v2(
            v2=fake,
            request=_Request(),
            body=_trigger_body(),
            authenticated=False,
        )

        first = await anext(stream)
        assert "response.created" in first

        advancing = asyncio.create_task(anext(stream))
        await asyncio.wait_for(state["started"].wait(), timeout=1)
        advancing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await advancing

        await asyncio.wait_for(state["cancelled"].wait(), timeout=1)
        worker = state["worker_task"]
        assert worker is not None
        assert worker.done()
        assert worker.cancelled()

    asyncio.run(scenario())


def test_aclose_after_progress_cleans_remote_compaction_worker():
    async def scenario():
        state = _state()
        fake = _blocking_v2(state)
        stream = remote._stream_remote_compaction_v2(
            v2=fake,
            request=_Request(),
            body=_trigger_body(),
            authenticated=False,
        )

        first = await anext(stream)
        assert "response.created" in first

        progress = asyncio.create_task(anext(stream))
        await asyncio.wait_for(state["started"].wait(), timeout=1)
        chunk = await asyncio.wait_for(progress, timeout=1)
        assert chunk

        await stream.aclose()
        await asyncio.wait_for(state["cancelled"].wait(), timeout=1)
        worker = state["worker_task"]
        assert worker is not None
        assert worker.done()
        assert worker.cancelled()

    asyncio.run(scenario())
