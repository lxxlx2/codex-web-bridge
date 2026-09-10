"""Codex Web Bridge V2: strict tools, wire observability and web-session affinity.

The V2 router is registered before the older Codex Responses adapter.  It keeps
that adapter as the compatibility fallback while owning streamed Codex tool
turns.  A Codex ``previous_response_id`` is bound to the ChatGPT ``/c/...``
conversation created by the corresponding browser round.  Continuations restore
that conversation and send only the new Responses delta instead of replaying the
entire transcript into a fresh web chat.

If the in-memory web binding is unavailable (UWA restart, TTL expiry, browser
navigation failure), V2 deliberately falls back to a fresh ChatGPT conversation
plus the reconstructed Responses history.  Correctness wins over affinity.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.chat import (
    ResponsesRequest,
    _build_responses_object,
    _new_response_id,
    _responses_completion_status_from_chat_payload,
    _responses_error_payload,
    _responses_request_to_chat_request,
    _run_chat_completion_final,
    _store_responses_state,
    verify_auth,
)
from app.api.codex_responses import (
    _codex_event,
    _codex_wire_item,
    _hydrate_codex_continuation,
    _persist_codex_history,
    _require_loopback,
    _sanitize_codex_root_workdirs,
    _sanitize_codex_tool_payload,
    codex_aware_responses,
)
from app.core.config import get_logger
from app.services.chatgpt_web_mode import (
    ChatGPTWebModeError,
    target_web_model,
    web_mode_enabled,
)
from app.services.codex_network_tuning import install_codex_chatgpt_network_tuning
from app.services.codex_metadata_helper import (
    build_metadata_json,
    classify_metadata_helper,
)
from app.services.codex_web_policy import (
    inspect_codex_web_mode_status,
    normalize_codex_reasoning,
    prepare_and_verify_codex_web_mode,
)
from app.services.codex_web_session_affinity import (
    affinity_status,
    bind_response_to_conversation,
    current_chatgpt_conversation_path,
    ensure_chatgpt_conversation,
    resolve_conversation_binding,
    set_codex_workflow_reuse_hint,
)
from app.services.codex_wire_observability import (
    new_trace_id,
    summarize_responses_request,
    summarize_responses_sse,
    trace_status,
    write_trace_attempt,
)


router = APIRouter()
logger = get_logger("API.CODEX_RESPONSES_V2")
_CODEX_SSE_KEEPALIVE_SEC = 5.0

_WORKSPACE_TOOL_NAMES = {
    "exec_command",
    "shell_command",
    "local_shell",
    "apply_patch",
    "write_stdin",
}

_REQUIRED_TOOL_PATTERNS = (
    re.compile(
        r"(?:必须|务必|一定要|必须通过|请务必|只能)\s*(?:通过|使用|调用)?\s*`?"
        r"(exec_command|shell_command|local_shell|apply_patch|write_stdin)`?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:must|required\s+to|have\s+to)\s+(?:use|call|invoke)\s+"
        r"(?:(?:the|a|an)\s+)?(?:(?:local|client|client-side|declared)\s+){0,3}`?"
        r"(exec_command|shell_command|local_shell|apply_patch|write_stdin)`?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[\n.!?]\s+)(?:first\s+)?(?:use|call|invoke)\s+"
        r"(?:(?:the|a|an)\s+)?(?:(?:local|client|client-side|declared)\s+){0,3}`?"
        r"(exec_command|shell_command|local_shell|apply_patch|write_stdin)`?\b",
        re.IGNORECASE,
    ),
)


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = str(os.getenv(name, str(default)) or str(default)).strip()
    try:
        value = int(raw)
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def _strict_retry_max() -> int:
    return _env_int("UWA_CODEX_REQUIRED_TOOL_RETRY_MAX", 1, 0, 3)


def _model_copy(body: ResponsesRequest) -> ResponsesRequest:
    if hasattr(body, "model_copy"):
        return body.model_copy(deep=True)
    return body.copy(deep=True)


def _declared_tool_names(tools: Any) -> List[str]:
    names: List[str] = []
    for item in tools if isinstance(tools, list) else []:
        if not isinstance(item, dict):
            continue
        function_data = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = str(function_data.get("name") or item.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _specific_tool_choice_name(tool_choice: Any) -> str:
    if not isinstance(tool_choice, dict):
        return ""
    if str(tool_choice.get("type") or "").strip().lower() != "function":
        return ""
    function_data = tool_choice.get("function") if isinstance(tool_choice.get("function"), dict) else {}
    return str(function_data.get("name") or tool_choice.get("name") or "").strip()


def _content_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        preferred = value.get("text")
        if isinstance(preferred, str):
            return preferred
        return "\n".join(_content_text(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return "\n".join(_content_text(item) for item in value)
    return ""


def _latest_user_text(source: Any) -> str:
    if isinstance(source, str):
        return source
    if not isinstance(source, list):
        return ""
    for item in reversed(source):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        item_type = str(item.get("type") or "").strip().lower()
        if role == "user" or (item_type == "message" and role == "user"):
            return _content_text(item.get("content"))
    return ""


def required_declared_tool(body: ResponsesRequest) -> str:
    declared = set(_declared_tool_names(body.tools))
    if not declared:
        return ""

    choice_name = _specific_tool_choice_name(body.tool_choice)
    if choice_name in declared:
        return choice_name

    user_text = _latest_user_text(body.input)
    for pattern in _REQUIRED_TOOL_PATTERNS:
        match = pattern.search(user_text)
        if not match:
            continue
        name = str(match.group(1) or "").strip()
        if name in declared:
            return name
    return ""


def _clone_for_required_tool_retry(
    body: ResponsesRequest,
    required_tool: str,
    attempt: int,
    *,
    previous_response_id: str,
) -> ResponsesRequest:
    """Build an incremental repair turn that stays in the same web conversation."""

    cloned = _model_copy(body)
    repair = (
        "[Codex V2 Required Tool Contract]\n"
        f"The previous answer did not emit the required real client function `{required_tool}`. "
        "Do not simulate command output and do not claim the declared tool is unavailable. "
        f"Emit an actual `{required_tool}` function call using the declared schema, then wait for "
        "the client tool result. For exec-like tools omit `workdir` unless the user explicitly "
        f"requested another working directory. Repair attempt: {attempt}."
    )
    cloned.instructions = None
    cloned.previous_response_id = str(previous_response_id or "").strip() or None
    cloned.input = [{"role": "user", "content": repair}]
    cloned.tool_choice = {"type": "function", "name": required_tool}
    return cloned


def _chunk_text(chunk: Any) -> str:
    if isinstance(chunk, bytes):
        return chunk.decode("utf-8", "replace")
    return str(chunk or "")


def _is_transport_comment(text: str) -> bool:
    stripped = str(text or "").lstrip()
    return stripped.startswith(":") and "event:" not in stripped and "data:" not in stripped


def _stream_headers() -> Dict[str, str]:
    return {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


def _pack_event(event: str, payload: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _summary_with_request_kind(
    body: ResponsesRequest,
    *,
    request_kind: str,
    required_tool: str = "",
) -> Dict[str, Any]:
    summary = summarize_responses_request(body, required_tool or None)
    summary["request_kind"] = request_kind
    return summary


async def _metadata_helper_stream(
    body: ResponsesRequest,
    trace_id: str,
) -> AsyncIterator[str]:
    """Answer known Codex UI metadata requests locally without touching ChatGPT Web."""

    response_id = _new_response_id()
    created_at = int(time.time())
    prompt = _latest_user_text(body.input)
    structured_text = build_metadata_json(prompt, body.text)
    chat_payload = {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": structured_text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    in_progress = _build_responses_object(
        body,
        {"choices": [], "usage": {}},
        response_id=response_id,
        created_at=created_at,
        status="in_progress",
        error=None,
    )
    completed = _build_responses_object(
        body,
        chat_payload,
        response_id=response_id,
        created_at=created_at,
        status="completed",
        error=None,
    )

    chunks: List[str] = []
    sequence = 1
    chunks.append(
        _codex_event(
            "response.created",
            sequence_number=sequence,
            response=in_progress,
        )
    )
    sequence += 1

    output = completed.get("output") if isinstance(completed.get("output"), list) else []
    for output_index, item in enumerate(output):
        if not isinstance(item, dict):
            continue
        chunks.append(
            _codex_event(
                "response.output_item.done",
                sequence_number=sequence,
                output_index=output_index,
                item=_codex_wire_item(item),
            )
        )
        sequence += 1

    chunks.append(
        _codex_event(
            "response.completed",
            sequence_number=sequence,
            response=completed,
        )
    )

    response_summary = summarize_responses_sse(chunks)
    response_summary["request_kind"] = "metadata_helper"
    write_trace_attempt(
        trace_id=trace_id,
        attempt=1,
        request_summary=_summary_with_request_kind(
            body,
            request_kind="metadata_helper",
        ),
        response_summary=response_summary,
        full_request=body,
        raw_sse="".join(chunks),
    )
    logger.info("[CODEX_RESPONSES_V2] metadata helper served locally")
    for chunk in chunks:
        yield chunk


def _required_tool_failed_events(body: ResponsesRequest, required_tool: str) -> List[str]:
    response_id = _new_response_id()
    created_at = int(time.time())
    in_progress = _build_responses_object(
        body,
        {"choices": [], "usage": {}},
        response_id=response_id,
        created_at=created_at,
        status="in_progress",
        error=None,
    )
    error = {
        "type": "invalid_tool_output",
        "code": "required_client_tool_not_called",
        "message": (
            f"The web model did not emit the explicitly required client tool `{required_tool}` "
            "after bounded repair attempts. Plain-text simulated tool output was rejected."
        ),
    }
    failed = _build_responses_object(
        body,
        {"choices": [], "usage": {}},
        response_id=response_id,
        created_at=created_at,
        status="failed",
        error=error,
    )
    return [
        _pack_event(
            "response.created",
            {"type": "response.created", "sequence_number": 1, "response": in_progress},
        ),
        _pack_event(
            "response.failed",
            {"type": "response.failed", "sequence_number": 2, "response": failed},
        ),
    ]


def _response_id_from_sse(chunks: List[str]) -> str:
    text = "".join(chunks)
    for block in re.split(r"\r?\n\r?\n", text):
        data_lines = [line[5:].lstrip() for line in block.splitlines() if line.startswith("data:")]
        if not data_lines:
            continue
        try:
            payload = json.loads("\n".join(data_lines))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        response = payload.get("response")
        if isinstance(response, dict):
            response_id = str(response.get("id") or "").strip()
            if response_id:
                return response_id
    return ""


def _browser_delta_request(body: ResponsesRequest) -> ResponsesRequest:
    """Remove server-side history handles before sending a continuation delta to the web UI."""

    cloned = _model_copy(body)
    cloned.previous_response_id = None
    cloned.instructions = None
    return cloned


def _prepare_codex_web_turn(body: ResponsesRequest) -> Tuple[ResponsesRequest, bool, str, str]:
    """Prepare browser state and return hydrated state body plus affinity metadata."""

    incoming_previous = str(body.previous_response_id or "").strip()
    reasoning = normalize_codex_reasoning(body.reasoning)
    web_model = target_web_model()
    binding = resolve_conversation_binding(
        incoming_previous,
        model=web_model,
        reasoning=reasoning,
    )

    reused = False
    reused_path = ""
    if binding is not None and ensure_chatgpt_conversation(binding.pathname):
        try:
            state = inspect_codex_web_mode_status(reasoning)
        except Exception:
            state = {"verified": False}
        if bool(state.get("verified")):
            reused = True
            reused_path = binding.pathname
            logger.info("[CODEX_WEB_AFFINITY] reusing mapped ChatGPT conversation (path redacted)")

    if not reused:
        prepare_and_verify_codex_web_mode(body.reasoning)
        if incoming_previous:
            logger.info(
                "[CODEX_WEB_AFFINITY] mapping unavailable/unhealthy; "
                "falling back to fresh chat plus reconstructed history"
            )

    hydrated = _hydrate_codex_continuation(body)
    install_codex_chatgpt_network_tuning()
    return hydrated, reused, reused_path, reasoning


async def _stream_codex_v2_attempt(
    *,
    request: Request,
    state_body: ResponsesRequest,
    browser_source_body: ResponsesRequest,
    reuse_web_conversation: bool,
    reused_path: str,
    reasoning: str,
    authenticated: bool,
) -> AsyncIterator[str]:
    """Execute one Codex browser turn and emit the minimal Responses SSE contract."""

    response_id = _new_response_id()
    created_at = int(time.time())
    sequence = 1
    state_chat_body = _responses_request_to_chat_request(state_body, stream=False)
    browser_body = (
        _responses_request_to_chat_request(_browser_delta_request(browser_source_body), stream=False)
        if reuse_web_conversation
        else state_chat_body
    )

    in_progress = _build_responses_object(
        state_body,
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

    set_codex_workflow_reuse_hint(True)
    task = asyncio.create_task(
        _run_chat_completion_final(
            request=request,
            body=browser_body,
            authenticated=authenticated,
        )
    )
    try:
        while not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=_CODEX_SSE_KEEPALIVE_SEC)
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
            state_body,
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
    finally:
        set_codex_workflow_reuse_hint(False)
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    payload = _sanitize_codex_root_workdirs(
        _sanitize_codex_tool_payload(raw_payload),
        state_chat_body.messages,
    )
    if status_code >= 400 or "error" in payload:
        failed = _build_responses_object(
            state_body,
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
        state_body,
        payload,
        response_id=response_id,
        created_at=created_at,
        status=response_status,
        error=None,
        incomplete_details=incomplete_details,
    )

    output = completed.get("output") if isinstance(completed.get("output"), list) else []
    tool_names: List[str] = []
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

    state_enabled = state_body.store is not False
    _store_responses_state(
        response_id,
        state_chat_body.messages,
        payload,
        enabled=state_enabled,
    )
    _persist_codex_history(
        response_id,
        state_chat_body.messages,
        payload,
        enabled=state_enabled,
    )

    path = current_chatgpt_conversation_path() or (reused_path if reuse_web_conversation else "")
    bind_response_to_conversation(
        response_id,
        path,
        model=target_web_model(),
        reasoning=reasoning,
    )

    logger.info(
        "[CODEX_RESPONSES_V2] stream completed: "
        f"response_id={response_id} output_items={len(output)} "
        f"tool_names={tool_names or ['none']} status={response_status} "
        f"web_session_reused={reuse_web_conversation} "
        f"browser_input={'delta' if reuse_web_conversation else 'full'}"
    )

    yield _codex_event(
        terminal_event,
        sequence_number=sequence,
        response=completed,
    )


async def _codex_web_attempt_response(
    *,
    request: Request,
    body: ResponsesRequest,
    authenticated: bool,
) -> StreamingResponse:
    incoming = _model_copy(body)
    state_body, reused, reused_path, reasoning = _prepare_codex_web_turn(body)
    return StreamingResponse(
        _stream_codex_v2_attempt(
            request=request,
            state_body=state_body,
            browser_source_body=incoming,
            reuse_web_conversation=reused,
            reused_path=reused_path,
            reasoning=reasoning,
            authenticated=authenticated,
        ),
        media_type="text/event-stream",
        headers=_stream_headers(),
    )


async def _trace_passthrough(
    *,
    response: StreamingResponse,
    body: ResponsesRequest,
    trace_id: str,
) -> AsyncIterator[str]:
    chunks: List[str] = []
    async for chunk in response.body_iterator:
        text = _chunk_text(chunk)
        chunks.append(text)
        yield text
    summary = summarize_responses_sse(chunks)
    summary["request_kind"] = "agent_turn"
    write_trace_attempt(
        trace_id=trace_id,
        attempt=1,
        request_summary=_summary_with_request_kind(
            body,
            request_kind="agent_turn",
        ),
        response_summary=summary,
        full_request=body,
        raw_sse="".join(chunks),
    )


async def _strict_required_tool_stream(
    *,
    request: Request,
    body: ResponsesRequest,
    authenticated: bool,
    required_tool: str,
    trace_id: str,
) -> AsyncIterator[str]:
    attempts = _strict_retry_max() + 1
    current_body = body

    for attempt in range(1, attempts + 1):
        response = await _codex_web_attempt_response(
            request=request,
            body=current_body,
            authenticated=authenticated,
        )

        buffered: List[str] = []
        async for chunk in response.body_iterator:
            text = _chunk_text(chunk)
            if _is_transport_comment(text):
                yield text
            else:
                buffered.append(text)

        response_summary = summarize_responses_sse(buffered)
        response_summary["request_kind"] = "agent_turn"
        names = response_summary.get("function_call_names") or []
        satisfied = required_tool in names
        response_summary["required_tool"] = required_tool
        response_summary["required_tool_satisfied"] = satisfied
        response_summary["strict_attempt"] = attempt

        request_summary = _summary_with_request_kind(
            current_body,
            request_kind="agent_turn",
            required_tool=required_tool,
        )
        request_summary["previous_response_id_present"] = bool(
            str(current_body.previous_response_id or "").strip()
        )
        write_trace_attempt(
            trace_id=trace_id,
            attempt=attempt,
            request_summary=request_summary,
            response_summary=response_summary,
            full_request=current_body,
            raw_sse="".join(buffered),
        )

        if satisfied:
            for text in buffered:
                yield text
            return

        attempt_response_id = _response_id_from_sse(buffered)
        if attempt < attempts and attempt_response_id:
            current_body = _clone_for_required_tool_retry(
                body,
                required_tool,
                attempt=attempt + 1,
                previous_response_id=attempt_response_id,
            )
            yield f": codex-v2-required-tool-retry attempt={attempt + 1}\n\n"
            continue

        for text in _required_tool_failed_events(body, required_tool):
            yield text
        return


@router.get("/v1/codex/wire-trace")
async def codex_wire_trace_status(request: Request) -> Dict[str, Any]:
    _require_loopback(request)
    return trace_status()


@router.get("/v1/codex/web-affinity")
async def codex_web_affinity_status(request: Request) -> Dict[str, Any]:
    _require_loopback(request)
    return affinity_status()


@router.post("/v1/responses")
async def codex_responses_v2(
    request: Request,
    body: ResponsesRequest,
    authenticated: bool = Depends(verify_auth),
):
    prompt = _latest_user_text(body.input)
    request_kind = classify_metadata_helper(prompt, body.text)
    if (
        request_kind == "metadata_helper"
        and str(body.model or "").strip().lower() == "chatgpt"
        and web_mode_enabled()
        and bool(body.stream)
    ):
        trace_id = new_trace_id()
        return StreamingResponse(
            _metadata_helper_stream(body, trace_id),
            media_type="text/event-stream",
            headers=_stream_headers(),
        )

    is_codex_web_tool_turn = (
        str(body.model or "").strip().lower() == "chatgpt"
        and web_mode_enabled()
        and bool(body.stream)
        and isinstance(body.tools, list)
        and bool(body.tools)
    )
    if not is_codex_web_tool_turn:
        return await codex_aware_responses(
            request=request,
            body=body,
            authenticated=authenticated,
        )

    trace_id = new_trace_id()
    required_tool = required_declared_tool(body)
    if required_tool:
        return StreamingResponse(
            _strict_required_tool_stream(
                request=request,
                body=body,
                authenticated=authenticated,
                required_tool=required_tool,
                trace_id=trace_id,
            ),
            media_type="text/event-stream",
            headers=_stream_headers(),
        )

    response = await _codex_web_attempt_response(
        request=request,
        body=body,
        authenticated=authenticated,
    )
    return StreamingResponse(
        _trace_passthrough(response=response, body=body, trace_id=trace_id),
        media_type="text/event-stream",
        headers=_stream_headers(),
    )


__all__ = [
    "codex_responses_v2",
    "required_declared_tool",
    "router",
]
