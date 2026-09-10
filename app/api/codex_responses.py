"""Codex-specific Responses bridge.

For the logical ``chatgpt`` browser route this layer prepares a fresh ChatGPT
composer, verifies the requested web reasoning mode, and applies ChatGPT-only
network budgets suitable for High reasoning.

For streamed Codex requests that expose client tools, it intentionally uses a
minimal Responses SSE sequence instead of translating the internal Chat
Completions tool stream event-by-event. This mirrors the event shape used by the
upstream Codex test harness and avoids leaking an intermediate browser refusal as
an assistant final message when a valid function call was recovered internally.

Codex continuation snapshots are also persisted privately under ~/.uwa by
default. The public repository never receives those snapshots.
"""

from __future__ import annotations

import asyncio
import copy
import ipaddress
import json
import time
from typing import Any, AsyncIterator, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.chat import (
    ResponsesRequest,
    _build_responses_object,
    _load_responses_state,
    _new_response_id,
    _responses_completion_status_from_chat_payload,
    _responses_error_payload,
    _responses_request_to_chat_request,
    _run_chat_completion_final,
    _store_responses_state,
    create_response as create_response_backing,
    verify_auth,
)
from app.core.config import get_logger
from app.services.chatgpt_web_mode import (
    ChatGPTWebModeError,
    inspect_chatgpt_web_mode_diagnostics,
    web_mode_enabled,
)
from app.services.client_tool_policy import user_explicitly_requested_root_workdir
from app.services.codex_network_tuning import install_codex_chatgpt_network_tuning
from app.services.codex_responses_state import (
    continuity_status,
    load_response_messages,
    store_response_messages,
)
from app.services.codex_web_policy import (
    inspect_codex_web_mode_status,
    prepare_and_verify_codex_web_mode,
)


router = APIRouter()
logger = get_logger("API.CODEX_RESPONSES")
_CODEX_SSE_KEEPALIVE_SEC = 5.0
_CODEX_EXEC_LIKE_TOOL_NAMES = {"exec_command", "shell_command", "local_shell"}


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(str(host or "").split("%", 1)[0]).is_loopback
    except ValueError:
        return str(host or "").casefold() == "localhost"


def _require_loopback(request: Request) -> None:
    host = request.client.host if request.client else ""
    if not _is_loopback(host):
        raise HTTPException(status_code=403, detail="Codex Web mode control is local-only")


def _copy_responses_request(body: ResponsesRequest) -> ResponsesRequest:
    if hasattr(body, "model_copy"):
        return body.model_copy(deep=True)
    return body.copy(deep=True)


def _input_contains_replayable_history(source: Any) -> bool:
    """Return True when the client already supplied more than a new-turn delta.

    This is only a last-resort fallback when both in-memory and persisted
    previous_response_id state are unavailable. A lone function_call_output is
    not sufficient because its matching function call may be missing.
    """

    if not isinstance(source, list) or len(source) < 2:
        return False
    has_user = False
    has_history = False
    for item in source:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        item_type = str(item.get("type") or "").strip().lower()
        if role == "user" or item_type == "message" and role == "user":
            has_user = True
        if role in {"assistant", "tool"} or item_type in {
            "function_call",
            "function_call_output",
            "tool_result",
        }:
            has_history = True
    return has_user and has_history


def _strip_duplicate_instruction(
    history: List[Dict[str, Any]],
    instructions: Any,
) -> List[Dict[str, Any]]:
    expected = str(instructions or "").strip()
    if not expected:
        return list(history)
    result = list(history)
    while result:
        first = result[0]
        if not isinstance(first, dict):
            break
        if str(first.get("role") or "").strip().lower() != "system":
            break
        if str(first.get("content") or "").strip() != expected:
            break
        result.pop(0)
    return result


def _hydrate_codex_continuation(body: ResponsesRequest) -> ResponsesRequest:
    """Recover a missing process-local previous_response_id from private SQLite.

    Normal in-process continuation keeps using the existing chat.py memory store.
    This fallback activates only after that state is absent/expired, which is the
    case we need for UWA process restarts.
    """

    previous_id = str(body.previous_response_id or "").strip()
    if not previous_id:
        return body

    try:
        _load_responses_state(previous_id)
        return body
    except HTTPException as exc:
        if exc.status_code != 404:
            raise

    persisted = load_response_messages(previous_id)
    if persisted is not None:
        cloned = _copy_responses_request(body)
        restored = _strip_duplicate_instruction(persisted, cloned.instructions)
        source = cloned.input
        combined: List[Any] = list(restored)
        if isinstance(source, list):
            combined.extend(source)
        elif source not in (None, ""):
            combined.append(source)
        cloned.input = combined
        cloned.previous_response_id = None
        logger.info(
            "[CODEX_CONTINUITY] restored previous_response_id from private local state: "
            f"messages={len(restored)}"
        )
        return cloned

    if _input_contains_replayable_history(body.input):
        cloned = _copy_responses_request(body)
        cloned.previous_response_id = None
        logger.warning(
            "[CODEX_CONTINUITY] previous_response_id missing, but client supplied "
            "replayable history; continuing from client transcript"
        )
        return cloned

    raise HTTPException(
        status_code=404,
        detail=f"previous_response_id not found or expired: {previous_id}",
    )


def _assistant_message_from_payload(payload: Dict[str, Any]) -> Dict[str, Any] | None:
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return None
    result = dict(message)
    result["role"] = "assistant"
    return result


def _persist_codex_history(
    response_id: str,
    request_messages: List[Dict[str, Any]],
    payload: Dict[str, Any],
    *,
    enabled: bool,
) -> None:
    if not enabled:
        return
    assistant = _assistant_message_from_payload(payload)
    if assistant is None:
        return
    history = list(request_messages or [])
    history.append(assistant)
    if not store_response_messages(response_id, history):
        logger.warning(
            "[CODEX_CONTINUITY] private persistence skipped; "
            "continuation remains process-local for this response"
        )


def _sanitize_codex_tool_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop contradictory assistant text when the same response contains real tool calls.

    Web models can emit a sentence such as "I cannot access the local tool" and
    still emit a valid XML/function call after UWA repair. Codex should receive
    the function call as the authoritative output for that round; user-facing
    prose belongs after the client returns the tool result.
    """

    clean = copy.deepcopy(payload if isinstance(payload, dict) else {})
    choices = clean.get("choices") if isinstance(clean.get("choices"), list) else []
    if not choices or not isinstance(choices[0], dict):
        return clean
    message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else None
    if not isinstance(message, dict):
        return clean
    tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
    if tool_calls:
        message["content"] = None
        # Media accompanying a recovered client tool call is not authoritative
        # tool output and should not turn this round into a final assistant item.
        message.pop("media", None)
        clean.pop("media", None)
    return clean


def _sanitize_codex_root_workdirs(
    payload: Dict[str, Any],
    request_messages: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Strip an accidental root workdir before any Codex Responses event is built.

    The browser model can guess ``workdir='/'`` even when Codex already has the
    correct native turn cwd.  Codex treats an absolute workdir as an override, so
    that guess would discard the project binding.  Unless the user explicitly
    requested filesystem root, remove only that exact override and let Codex use
    its authoritative turn cwd.  Command bodies are never logged here.
    """

    clean = copy.deepcopy(payload if isinstance(payload, dict) else {})
    if user_explicitly_requested_root_workdir(request_messages):
        return clean

    choices = clean.get("choices") if isinstance(clean.get("choices"), list) else []
    stripped = 0
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message") if isinstance(choice.get("message"), dict) else None
        if not isinstance(message, dict):
            continue
        tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            function_data = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else None
            if not isinstance(function_data, dict):
                continue
            tool_name = str(function_data.get("name") or "").strip()
            if tool_name not in _CODEX_EXEC_LIKE_TOOL_NAMES:
                continue
            raw_arguments = function_data.get("arguments")
            if isinstance(raw_arguments, dict):
                arguments = dict(raw_arguments)
            elif isinstance(raw_arguments, str):
                try:
                    decoded = json.loads(raw_arguments)
                except Exception:
                    continue
                if not isinstance(decoded, dict):
                    continue
                arguments = decoded
            else:
                continue
            if str(arguments.get("workdir") or "").strip() != "/":
                continue
            arguments.pop("workdir", None)
            function_data["arguments"] = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
            stripped += 1

    if stripped:
        logger.warning(
            "[CODEX_RESPONSES] stripped accidental root workdir before Codex delivery: "
            f"count={stripped}; command bodies not logged"
        )
    return clean


def _codex_wire_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Return the conservative Responses item shape Codex itself uses in tests."""

    item_type = str(item.get("type") or "").strip().lower()
    if item_type == "function_call":
        return {
            "type": "function_call",
            "call_id": str(item.get("call_id") or ""),
            "name": str(item.get("name") or ""),
            "arguments": str(item.get("arguments") or "{}"),
        }
    if item_type == "message":
        wire = {
            "type": "message",
            "role": str(item.get("role") or "assistant"),
            "content": item.get("content") if isinstance(item.get("content"), list) else [],
        }
        if item.get("id"):
            wire["id"] = item.get("id")
        return wire
    return dict(item)


def _pack_codex_sse(event: str, payload: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _codex_event(event: str, *, sequence_number: int, **fields: Any) -> str:
    payload: Dict[str, Any] = {
        "type": event,
        "sequence_number": sequence_number,
        **fields,
    }
    return _pack_codex_sse(event, payload)


async def _stream_codex_minimal_responses(
    *,
    request: Request,
    body: ResponsesRequest,
    authenticated: bool,
) -> AsyncIterator[str]:
    """Run the browser/tool adapter to completion, then emit minimal Codex SSE.

    The browser may need tens of seconds to reason. Keepalive comments preserve
    the HTTP stream while the internal non-stream Chat Completions tool adapter
    performs refusal repair and tool-call validation.
    """

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
    yield _codex_event(
        "response.created",
        sequence_number=sequence,
        response=in_progress,
    )
    sequence += 1

    task = asyncio.create_task(
        _run_chat_completion_final(
            request=request,
            body=chat_body,
            authenticated=authenticated,
        )
    )
    try:
        while not task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=_CODEX_SSE_KEEPALIVE_SEC,
                )
            except asyncio.TimeoutError:
                if await request.is_disconnected():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    return
                yield ": keepalive\n\n"

        status_code, raw_payload = task.result()
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
        yield _codex_event(
            "response.failed",
            sequence_number=sequence,
            response=failed,
        )
        return

    payload = _sanitize_codex_root_workdirs(
        _sanitize_codex_tool_payload(raw_payload),
        chat_body.messages,
    )
    if status_code >= 400 or "error" in payload:
        failed = _build_responses_object(
            body,
            payload,
            response_id=response_id,
            created_at=created_at,
            status="failed",
            error=_responses_error_payload(payload),
        )
        yield _codex_event(
            "response.failed",
            sequence_number=sequence,
            response=failed,
        )
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
    tool_names = []
    for output_index, item in enumerate(output):
        if not isinstance(item, dict):
            continue
        wire_item = _codex_wire_item(item)
        if wire_item.get("type") == "function_call":
            tool_names.append(str(wire_item.get("name") or ""))
        yield _codex_event(
            "response.output_item.done",
            sequence_number=sequence,
            output_index=output_index,
            item=wire_item,
        )
        sequence += 1

    state_enabled = body.store is not False
    _store_responses_state(
        response_id,
        chat_body.messages,
        payload,
        enabled=state_enabled,
    )
    _persist_codex_history(
        response_id,
        chat_body.messages,
        payload,
        enabled=state_enabled,
    )

    logger.info(
        "[CODEX_RESPONSES] minimal stream completed: "
        f"response_id={response_id} output_items={len(output)} "
        f"tool_names={tool_names or ['none']} status={response_status}"
    )

    yield _codex_event(
        terminal_event,
        sequence_number=sequence,
        response=completed,
    )


class CodexWebModeApplyRequest(BaseModel):
    reasoning: str = "high"


@router.get("/v1/codex/web-mode")
async def codex_web_mode_status(request: Request) -> Dict[str, object]:
    _require_loopback(request)
    try:
        return inspect_codex_web_mode_status()
    except ChatGPTWebModeError as exc:
        return {
            "enabled": web_mode_enabled(),
            "verified": False,
            "error": str(exc),
        }


@router.get("/v1/codex/web-mode/diagnostics")
async def codex_web_mode_diagnostics(request: Request) -> Dict[str, object]:
    """Return sanitized model/mode UI metadata for the local controlled tab only."""
    _require_loopback(request)
    try:
        return inspect_chatgpt_web_mode_diagnostics()
    except ChatGPTWebModeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/v1/codex/web-mode/apply")
async def codex_web_mode_apply(
    request: Request,
    payload: CodexWebModeApplyRequest,
) -> Dict[str, object]:
    _require_loopback(request)
    try:
        return prepare_and_verify_codex_web_mode(payload.reasoning)
    except ChatGPTWebModeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/v1/codex/continuity")
async def codex_continuity_status(request: Request) -> Dict[str, object]:
    """Return local-only continuation metadata without stored conversation content."""
    _require_loopback(request)
    return continuity_status()


@router.post("/v1/responses")
async def codex_aware_responses(
    request: Request,
    body: ResponsesRequest,
    authenticated: bool = Depends(verify_auth),
):
    is_codex_web = str(body.model or "").strip().lower() == "chatgpt" and web_mode_enabled()
    if is_codex_web:
        body = _hydrate_codex_continuation(body)
        install_codex_chatgpt_network_tuning()
        try:
            prepare_and_verify_codex_web_mode(body.reasoning)
        except ChatGPTWebModeError as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "chatgpt_web_mode_verification_failed",
                    "message": str(exc),
                },
            ) from exc

        # Codex currently sends its local client functions in every agent turn.
        # For those streamed tool-capable turns, emit the smallest Responses SSE
        # shape known to be consumed by Codex reliably. Ordinary no-tool requests
        # retain the generic Responses adapter for compatibility.
        if bool(body.stream) and isinstance(body.tools, list) and body.tools:
            return StreamingResponse(
                _stream_codex_minimal_responses(
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

    return await create_response_backing(
        request=request,
        body=body,
        authenticated=authenticated,
    )
