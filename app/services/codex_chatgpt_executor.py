"""Codex-only non-stream ChatGPT Web execution seam.

The Codex Responses bridge always asks its backing chat worker for a final
non-stream OpenAI-compatible payload. The historical Universal Web API chat
entrypoint performed generic model discovery and provider routing before it ever
reached the ChatGPT tab. Standalone only exposes the logical ``chatgpt`` route,
so that generic routing layer is unnecessary here.

This module preserves the validated request-manager lifecycle, tracked blocking
worker cleanup, tool-calling repair loop, response-format prompting and browser
workflow implementation while selecting the controlled ``chatgpt.com`` route
explicitly. It does not execute client tools: tool calls remain model output for
Codex Desktop/CLI to execute under the client's sandbox and approval policy.
"""

from __future__ import annotations

import asyncio
import copy
import json
import threading
from typing import Any, Dict, List, Optional

from fastapi import Request

from app.api.codex_runtime import ChatRequest
from app.api.openai_stop import apply_stop_sequences_to_text
from app.core import get_browser
from app.core.config import get_logger
from app.services.error_metadata import resolve_error_metadata
from app.services.request_lifecycle import (
    TrackedWorkerExecutionCancelled,
    cleanup_worker_thread_after_request,
    run_tracked_blocking_call,
)
from app.services.request_manager import (
    RequestContext,
    RequestStatus,
    cancel_storm_guard,
    request_manager,
    watch_client_disconnect,
)
from app.services.tool_calling import (
    build_tool_completion_response,
    complete_tool_calling_roundtrip_async,
    decode_browser_non_stream_payload,
    extract_tool_calling_assistant_content,
    get_tool_calling_allow_media_postprocess,
    has_tool_calling_request,
    normalize_tool_request,
)


logger = get_logger("CODEX.CHATGPT.EXECUTOR")
CHATGPT_ROUTE_DOMAIN = "chatgpt.com"
WORKER_POLL_SECONDS = 0.5

_RESPONSE_FORMAT_HINTS = {
    "json_object": (
        "\n\n[System instruction: Return a valid JSON object only. "
        "Do not wrap it in a Markdown code fence or add non-JSON text.]"
    ),
    "json_schema": (
        "\n\n[System instruction: Return valid JSON that strictly follows this JSON Schema. "
        "Do not wrap it in a Markdown code fence:\n{schema}]"
    ),
    "text": "",
}


class CodexChatGPTExecutionError(RuntimeError):
    """Structured execution failure that keeps the backing HTTP status."""

    def __init__(self, message: str, *, code: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.code = str(code or "codex_chatgpt_execution_failed")
        self.status_code = max(400, int(status_code or 500))


def _error_payload(message: str, code: str) -> Dict[str, Any]:
    return {
        "error": {
            "message": str(message or code or "Codex ChatGPT execution failed"),
            "type": "execution_error",
            "code": str(code or "codex_chatgpt_execution_failed"),
        }
    }


def _manual_cancelled(ctx: RequestContext) -> bool:
    reason = str(getattr(ctx, "cancel_reason", "") or "").strip().lower()
    return reason in {
        "manual",
        "manual_terminate",
        "user_cancel",
        "user_cancelled",
        "cancel_button",
    }


def _browser_payload_error(data: Dict[str, Any]) -> Optional[CodexChatGPTExecutionError]:
    if not isinstance(data, dict) or "error" not in data:
        return None
    meta = resolve_error_metadata(data)
    if meta is not None:
        return CodexChatGPTExecutionError(
            str(meta.message or "ChatGPT Web execution failed"),
            code=str(meta.code or "browser_execution_failed"),
            status_code=int(meta.status_code or 500),
        )
    error = data.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "browser_execution_failed")
        code = str(error.get("code") or "browser_execution_failed")
        try:
            status_code = int(error.get("status_code") or 500)
        except (TypeError, ValueError):
            status_code = 500
        return CodexChatGPTExecutionError(message, code=code, status_code=status_code)
    return CodexChatGPTExecutionError(
        str(error or "browser_execution_failed"),
        code="browser_execution_failed",
        status_code=500,
    )


def _response_format_hint(response_format: Any) -> str:
    if not isinstance(response_format, dict) or not response_format:
        return ""
    format_type = str(response_format.get("type") or "text").strip().lower() or "text"
    template = _RESPONSE_FORMAT_HINTS.get(format_type, "")
    if not template:
        return ""
    if format_type != "json_schema":
        return template

    json_schema = response_format.get("json_schema", {})
    schema_content = (
        json_schema.get("schema", json_schema)
        if isinstance(json_schema, dict)
        else json_schema
    )
    try:
        schema_text = json.dumps(schema_content, ensure_ascii=False, indent=2)
    except Exception:
        schema_text = str(schema_content)
    return template.replace("{schema}", schema_text)


def _apply_response_format(messages: List[Dict[str, Any]], response_format: Any) -> List[Dict[str, Any]]:
    """Append the Responses format contract to the latest user text part."""

    hint = _response_format_hint(response_format)
    if not hint:
        return messages

    updated = copy.deepcopy(messages)
    for message in reversed(updated):
        if not isinstance(message, dict) or str(message.get("role") or "") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            message["content"] = content + hint
            return updated
        if isinstance(content, list):
            for item in reversed(content):
                if isinstance(item, dict) and str(item.get("type") or "") == "text":
                    item["text"] = str(item.get("text") or "") + hint
                    return updated
            content.append({"type": "text", "text": hint})
            return updated
    return updated


def _body_with_response_format_hint(body: ChatRequest) -> ChatRequest:
    messages = _apply_response_format(body.messages, body.response_format)
    if messages is body.messages:
        return body
    return body.model_copy(update={"messages": messages})


def _execute_browser_non_stream_messages(
    browser: Any,
    messages: List[Dict[str, Any]],
    request_id: str,
    *,
    stop_checker=None,
    requested_model: Optional[str] = None,
) -> Dict[str, Any]:
    """Run one browser round on the controlled ChatGPT route."""

    payload: Any = None
    for chunk in browser.execute_workflow_for_route_domain(
        CHATGPT_ROUTE_DOMAIN,
        messages,
        stream=False,
        task_id=request_id,
        stop_checker=stop_checker,
        allow_media_postprocess=get_tool_calling_allow_media_postprocess(),
        requested_model=requested_model,
    ):
        payload = chunk

    data = decode_browser_non_stream_payload(payload)
    error = _browser_payload_error(data)
    if error is not None:
        raise error
    return data


def _assistant_content(response: Dict[str, Any]) -> str:
    try:
        return extract_tool_calling_assistant_content(response)
    except Exception:
        return ""


async def _run_tracked_round(
    worker_fn,
    *,
    ctx: RequestContext,
    worker_state: Dict[str, Any],
    label: str,
) -> Any:
    try:
        return await run_tracked_blocking_call(
            worker_fn,
            ctx=ctx,
            worker_state=worker_state,
            label=label,
            poll_timeout=WORKER_POLL_SECONDS,
        )
    except TrackedWorkerExecutionCancelled as exc:
        reason = str(exc or getattr(ctx, "cancel_reason", "") or "tool_calling_cancelled")
        raise CodexChatGPTExecutionError(
            reason,
            code=reason,
            status_code=500 if reason == "absolute_request_timeout" else 499,
        ) from exc


async def _run_tool_calling(
    browser: Any,
    body: ChatRequest,
    ctx: RequestContext,
    worker_state: Dict[str, Any],
) -> Dict[str, Any]:
    legacy_function_call = bool(body.functions) and not bool(body.tools)
    tools, tool_choice = normalize_tool_request(
        tools=body.tools,
        tool_choice=body.tool_choice,
        functions=body.functions,
        function_call=body.function_call,
    )

    async def _round_executor(browser_messages: List[Dict[str, str]]) -> str:
        worker_fn = lambda: _assistant_content(
            _execute_browser_non_stream_messages(
                browser,
                browser_messages,
                ctx.request_id,
                stop_checker=ctx.should_stop,
                requested_model=body.model,
            )
        )
        return str(
            await _run_tracked_round(
                worker_fn,
                ctx=ctx,
                worker_state=worker_state,
                label=f"{ctx.request_id[:8]}-round",
            )
            or ""
        )

    parsed = await complete_tool_calling_roundtrip_async(
        messages=body.messages,
        tools=tools,
        tool_choice=tool_choice,
        parallel_tool_calls=(False if legacy_function_call else body.parallel_tool_calls),
        round_executor=_round_executor,
        stop_checker=ctx.should_stop,
    )
    if not parsed.get("tool_calls"):
        parsed = dict(parsed)
        parsed["content"] = apply_stop_sequences_to_text(
            str(parsed.get("content") or ""),
            body.stop,
        )
    return build_tool_completion_response(
        body.model,
        parsed,
        legacy_function_call=legacy_function_call,
    )


def _apply_stop_to_final_payload(payload: Dict[str, Any], stop: Any) -> Dict[str, Any]:
    if stop in (None, "", []):
        return payload
    result = dict(payload)
    choices = result.get("choices")
    if not isinstance(choices, list):
        return result
    next_choices: List[Any] = []
    for choice in choices:
        if not isinstance(choice, dict):
            next_choices.append(choice)
            continue
        next_choice = dict(choice)
        message = next_choice.get("message")
        if isinstance(message, dict):
            next_message = dict(message)
            content = next_message.get("content")
            if isinstance(content, str):
                next_message["content"] = apply_stop_sequences_to_text(content, stop)
            next_choice["message"] = next_message
        next_choices.append(next_choice)
    result["choices"] = next_choices
    return result


async def execute_chatgpt_nonstream(
    *,
    request: Request,
    body: ChatRequest,
    authenticated: bool,
) -> tuple[int, Dict[str, Any]]:
    """Execute the backing request without generic provider/model routing."""

    del authenticated
    effective_body = _body_with_response_format_hint(body)
    client_fp = cancel_storm_guard.get_client_fingerprint(request)
    await cancel_storm_guard.maybe_backoff(client_fp)
    ctx = request_manager.create_request(client_fp=client_fp)
    worker_state: Dict[str, Any] = {"thread": None, "label": None, "ctx": ctx}
    disconnect_task = None

    try:
        await asyncio.to_thread(
            request_manager.record_request_input,
            ctx,
            effective_body.model_dump(),
            endpoint="/v1/responses:chatgpt-backing",
            route_domain=CHATGPT_ROUTE_DOMAIN,
            preset_name=effective_body.preset_name,
        )
        request_manager.start_request(ctx)
        disconnect_task = asyncio.create_task(
            watch_client_disconnect(request, ctx, check_interval=0.3)
        )
        browser = get_browser(auto_connect=False)

        if has_tool_calling_request(
            messages=effective_body.messages,
            tools=effective_body.tools,
            functions=effective_body.functions,
        ):
            payload = await _run_tool_calling(browser, effective_body, ctx, worker_state)
        else:
            worker_fn = lambda: _execute_browser_non_stream_messages(
                browser,
                effective_body.messages,
                ctx.request_id,
                stop_checker=ctx.should_stop,
                requested_model=effective_body.model,
            )
            payload = await _run_tracked_round(
                worker_fn,
                ctx=ctx,
                worker_state=worker_state,
                label=f"{ctx.request_id[:8]}-final",
            )
            payload = _apply_stop_to_final_payload(payload, effective_body.stop)

        if ctx.should_stop():
            reason = str(ctx.cancel_reason or "request_cancelled")
            status = 499 if reason != "absolute_request_timeout" else 500
            raise CodexChatGPTExecutionError(reason, code=reason, status_code=status)

        request_manager.capture_response_payload(ctx, payload)
        if ctx.status == RequestStatus.RUNNING:
            ctx.mark_completed()
        return 200, payload

    except asyncio.CancelledError:
        if not ctx.should_stop():
            ctx.request_cancel("coroutine_cancelled")
        raise
    except CodexChatGPTExecutionError as exc:
        if ctx.status not in {RequestStatus.COMPLETED, RequestStatus.CANCELLED}:
            try:
                ctx.mark_failed(str(exc))
            except Exception:
                pass
        request_manager.capture_error(ctx, str(exc), code=exc.code)
        return exc.status_code, _error_payload(str(exc), exc.code)
    except Exception as exc:
        if _manual_cancelled(ctx):
            code = str(ctx.cancel_reason or "manual_terminate")
            return 499, _error_payload("request cancelled", code)
        logger.exception("Codex ChatGPT backing execution failed")
        try:
            ctx.mark_failed(str(exc))
        except Exception:
            pass
        request_manager.capture_error(ctx, exc, code="codex_chatgpt_execution_failed")
        return 500, _error_payload(str(exc), "codex_chatgpt_execution_failed")
    finally:
        if disconnect_task is not None:
            disconnect_task.cancel()
            try:
                await disconnect_task
            except asyncio.CancelledError:
                pass

        worker_thread = worker_state.get("thread")
        if isinstance(worker_thread, threading.Thread) and worker_thread.is_alive():
            await cleanup_worker_thread_after_request(
                worker_thread,
                ctx,
                completed=ctx.status == RequestStatus.COMPLETED,
                cancel_reason="cleanup",
                join_timeout=5.0,
                retire_reason="worker_cleanup_timeout",
            )
        worker_state["thread"] = None
        worker_state["label"] = None
        request_manager.finish_request(
            ctx,
            success=(ctx.status == RequestStatus.COMPLETED),
        )


__all__ = [
    "CHATGPT_ROUTE_DOMAIN",
    "CodexChatGPTExecutionError",
    "_apply_response_format",
    "_execute_browser_non_stream_messages",
    "_run_tool_calling",
    "execute_chatgpt_nonstream",
]
