"""Standalone Responses fallback built on the extracted ChatGPT executor.

Codex V2 owns normal streamed tool turns. This module covers the remaining
Responses compatibility path without entering the integrated UWA chat router.
"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Dict

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.codex_runtime import (
    ResponsesRequest,
    _build_responses_object,
    _new_response_id,
    _responses_completion_status_from_chat_payload,
    _responses_error_payload,
    _responses_request_to_chat_request,
    _store_responses_state,
)
from app.services.codex_chatgpt_executor import execute_chatgpt_nonstream


def _pack_event(event: str, sequence_number: int, **fields: Any) -> str:
    payload: Dict[str, Any] = {
        "type": event,
        "sequence_number": sequence_number,
        **fields,
    }
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream_response(
    *,
    request: Request,
    body: ResponsesRequest,
    authenticated: bool,
) -> AsyncIterator[str]:
    response_id = _new_response_id()
    created_at = int(time.time())
    sequence = 1
    chat_body = _responses_request_to_chat_request(body, stream=False)

    in_progress = _build_responses_object(
        body,
        {"choices": [], "usage": {}},
        response_id=response_id,
        created_at=created_at,
        status="in_progress",
        error=None,
    )
    yield _pack_event(
        "response.created",
        sequence,
        response=in_progress,
    )
    sequence += 1

    try:
        status_code, payload = await execute_chatgpt_nonstream(
            request=request,
            body=chat_body,
            authenticated=authenticated,
        )
    except Exception as exc:
        failed = _build_responses_object(
            body,
            {"choices": [], "usage": {}},
            response_id=response_id,
            created_at=created_at,
            status="failed",
            error={
                "message": str(exc),
                "type": "execution_error",
                "code": "responses_backing_request_failed",
            },
        )
        yield _pack_event("response.failed", sequence, response=failed)
        return

    if status_code >= 400 or "error" in payload:
        failed = _build_responses_object(
            body,
            payload,
            response_id=response_id,
            created_at=created_at,
            status="failed",
            error=_responses_error_payload(payload),
        )
        yield _pack_event("response.failed", sequence, response=failed)
        return

    response_status, incomplete_details, terminal_event = (
        _responses_completion_status_from_chat_payload(payload)
    )
    completed = _build_responses_object(
        body,
        payload,
        response_id=response_id,
        created_at=created_at,
        status=response_status,
        error=None,
        incomplete_details=incomplete_details,
    )

    output = completed.get("output") if isinstance(completed.get("output"), list) else []
    for output_index, item in enumerate(output):
        if not isinstance(item, dict):
            continue
        yield _pack_event(
            "response.output_item.done",
            sequence,
            output_index=output_index,
            item=item,
        )
        sequence += 1

    _store_responses_state(
        response_id,
        chat_body.messages,
        payload,
        enabled=body.store is not False,
    )
    yield _pack_event(terminal_event, sequence, response=completed)


async def create_response(
    *,
    request: Request,
    body: ResponsesRequest,
    authenticated: bool,
):
    """Serve the fallback Responses path through the standalone executor."""

    if body.stream:
        return StreamingResponse(
            _stream_response(
                request=request,
                body=body,
                authenticated=authenticated,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    chat_body = _responses_request_to_chat_request(body, stream=False)
    try:
        status_code, payload = await execute_chatgpt_nonstream(
            request=request,
            body=chat_body,
            authenticated=authenticated,
        )
    except Exception as exc:
        failed = _build_responses_object(
            body,
            {"choices": [], "usage": {}},
            status="failed",
            error={
                "message": str(exc),
                "type": "execution_error",
                "code": "responses_backing_request_failed",
            },
        )
        return JSONResponse(content=failed, status_code=500)

    if status_code >= 400 or "error" in payload:
        failed = _build_responses_object(
            body,
            payload,
            status="failed",
            error=_responses_error_payload(payload),
        )
        return JSONResponse(content=failed, status_code=status_code)

    response_status, incomplete_details, _terminal_event = (
        _responses_completion_status_from_chat_payload(payload)
    )
    response_obj = _build_responses_object(
        body,
        payload,
        status=response_status,
        error=None,
        incomplete_details=incomplete_details,
    )
    _store_responses_state(
        str(response_obj.get("id") or ""),
        chat_body.messages,
        payload,
        enabled=body.store is not False,
    )
    return JSONResponse(content=response_obj)


__all__ = ["create_response"]
