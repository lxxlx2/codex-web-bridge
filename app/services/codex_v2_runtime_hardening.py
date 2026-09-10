"""Runtime guardrails for the Codex Web Bridge V2 streaming path.

The browser bridge is layered on optional local facilities such as wire tracing,
Responses continuation snapshots and in-process web-session affinity. None of
those helpers may tear down the HTTP stream after ChatGPT Web produced a result.

This module also repairs two Codex continuation shapes seen in live macOS runs:

* a strict required-tool repair can reuse an already-bound ChatGPT conversation
  even when local Responses hydration fails;
* Codex may return a full-history ``function_call_output`` request without a
  usable ``previous_response_id``. The bridge remembers only ``call_id ->
  response_id`` metadata so that tool output can return to the same web
  conversation and so an already-completed required tool is not forced again.

The guard is process-local and idempotent. It stores no prompt, command, tool
result, cookie or browser credential.
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Set, Tuple

from fastapi.responses import StreamingResponse

from app.api.chat import ResponsesRequest, _build_responses_object, _new_response_id
from app.api.codex_responses import _codex_event
from app.core.config import get_logger


logger = get_logger("CODEX_V2_RUNTIME")
_INSTALLED = False
_CALL_RESPONSE_LOCK = threading.RLock()
_CALL_RESPONSE_IDS: "OrderedDict[str, Tuple[float, str]]" = OrderedDict()
_CALL_RESPONSE_TTL_SEC = 7200.0
_CALL_RESPONSE_MAX = 4096


def _model_copy(body: ResponsesRequest) -> ResponsesRequest:
    if hasattr(body, "model_copy"):
        return body.model_copy(deep=True)
    return body.copy(deep=True)


def _compact_failure_body(body: ResponsesRequest) -> ResponsesRequest:
    compact = _model_copy(body)
    compact.input = ""
    compact.instructions = None
    compact.previous_response_id = None
    compact.tools = None
    compact.tool_choice = None
    compact.metadata = None
    compact.prompt = None
    compact.user = None
    return compact


def _degraded_reuse_state_body(body: ResponsesRequest) -> ResponsesRequest:
    cloned = _model_copy(body)
    cloned.previous_response_id = None
    cloned.instructions = None
    return cloned


def _item_type(item: Any) -> str:
    return str(item.get("type") or "").strip().lower() if isinstance(item, dict) else ""


def _item_call_id(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    return str(
        item.get("call_id")
        or item.get("tool_call_id")
        or item.get("id")
        or ""
    ).strip()


def _item_function_name(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    function_data = item.get("function") if isinstance(item.get("function"), dict) else {}
    return str(item.get("name") or function_data.get("name") or "").strip()


def _latest_user_index(source: Any) -> int:
    if not isinstance(source, list):
        return -1
    for index in range(len(source) - 1, -1, -1):
        item = source[index]
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role == "user":
            return index
    return -1


def _function_call_output_ids(source: Any) -> List[str]:
    ids: List[str] = []
    for item in source if isinstance(source, list) else []:
        if _item_type(item) not in {"function_call_output", "tool_result"}:
            continue
        call_id = _item_call_id(item)
        if call_id and call_id not in ids:
            ids.append(call_id)
    return ids


def _completed_function_call_names(source: Any) -> Set[str]:
    if not isinstance(source, list):
        return set()

    latest_user = _latest_user_index(source)
    if latest_user < 0:
        return set()

    calls: Dict[str, str] = {}
    outputs: Set[str] = set()
    for item in source[latest_user + 1 :]:
        item_type = _item_type(item)
        if item_type in {"function_call", "tool_call"}:
            call_id = _item_call_id(item)
            name = _item_function_name(item)
            if call_id and name:
                calls[call_id] = name
        elif item_type in {"function_call_output", "tool_result"}:
            call_id = _item_call_id(item)
            if call_id:
                outputs.add(call_id)

    return {
        calls[call_id]
        for call_id in outputs
        if call_id in calls and calls[call_id]
    }


def _tool_result_delta_body(body: ResponsesRequest) -> ResponsesRequest:
    cloned = _model_copy(body)
    cloned.previous_response_id = None
    cloned.instructions = None
    if isinstance(cloned.input, list):
        outputs = [
            item
            for item in cloned.input
            if _item_type(item) in {"function_call_output", "tool_result"}
        ]
        if outputs:
            cloned.input = outputs
    return cloned


def _prune_call_response_ids_locked(now: Optional[float] = None) -> None:
    current = float(now if now is not None else time.time())
    cutoff = current - _CALL_RESPONSE_TTL_SEC
    expired = [key for key, value in _CALL_RESPONSE_IDS.items() if value[0] < cutoff]
    for key in expired:
        _CALL_RESPONSE_IDS.pop(key, None)
    while len(_CALL_RESPONSE_IDS) > _CALL_RESPONSE_MAX:
        _CALL_RESPONSE_IDS.popitem(last=False)


def _remember_call_response(call_ids: List[str], response_id: str) -> None:
    response_key = str(response_id or "").strip()
    if not response_key:
        return
    safe_ids = [str(call_id or "").strip() for call_id in call_ids if str(call_id or "").strip()]
    if not safe_ids:
        return
    now = time.time()
    with _CALL_RESPONSE_LOCK:
        _prune_call_response_ids_locked(now)
        for call_id in safe_ids:
            existing = _CALL_RESPONSE_IDS.get(call_id)
            if existing is None:
                _CALL_RESPONSE_IDS[call_id] = (now, response_key)
            else:
                existing_response = str(existing[1] or "").strip()
                if not existing_response:
                    _CALL_RESPONSE_IDS[call_id] = (now, "")
                elif existing_response == response_key:
                    _CALL_RESPONSE_IDS[call_id] = (now, response_key)
                else:
                    _CALL_RESPONSE_IDS[call_id] = (now, "")
                    logger.warning(
                        "[CODEX_V2_RUNTIME] fenced conflicting call_id continuation identity; "
                        "affinity resolution disabled for this call id"
                    )
            _CALL_RESPONSE_IDS.move_to_end(call_id)
        _prune_call_response_ids_locked(now)


def _resolve_call_response(call_ids: List[str]) -> str:
    keys = [str(call_id or "").strip() for call_id in call_ids if str(call_id or "").strip()]
    with _CALL_RESPONSE_LOCK:
        _prune_call_response_ids_locked()
        for call_id in keys:
            value = _CALL_RESPONSE_IDS.get(call_id)
            if value is not None and not str(value[1] or "").strip():
                _CALL_RESPONSE_IDS.move_to_end(call_id)
                return ""
        for call_id in reversed(keys):
            value = _CALL_RESPONSE_IDS.get(call_id)
            if value is not None:
                _CALL_RESPONSE_IDS.move_to_end(call_id)
                return str(value[1] or "").strip()
    return ""


def _response_and_call_ids_from_sse(chunks: List[str]) -> Tuple[str, List[str]]:
    response_id = ""
    call_ids: List[str] = []
    for block in "".join(chunks).replace("\r\n", "\n").split("\n\n"):
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
        if isinstance(response, dict) and not response_id:
            response_id = str(response.get("id") or "").strip()
        item = payload.get("item")
        if isinstance(item, dict) and _item_type(item) == "function_call":
            call_id = _item_call_id(item)
            if call_id and call_id not in call_ids:
                call_ids.append(call_id)
    return response_id, call_ids


def _failure_events(
    body: ResponsesRequest,
    *,
    code: str,
    exc: BaseException,
) -> List[str]:
    compact = _compact_failure_body(body)
    response_id = _new_response_id()
    created_at = int(time.time())
    in_progress = _build_responses_object(
        compact,
        {"choices": [], "usage": {}},
        response_id=response_id,
        created_at=created_at,
        status="in_progress",
        error=None,
    )
    failed = _build_responses_object(
        compact,
        {"choices": [], "usage": {}},
        response_id=response_id,
        created_at=created_at,
        status="failed",
        error={
            "message": (
                "Codex Web Bridge V2 terminated the browser attempt safely after an "
                f"internal {type(exc).__name__}. Check the private local UWA log."
            ),
            "type": "execution_error",
            "code": code,
        },
    )
    return [
        _codex_event("response.created", sequence_number=1, response=in_progress),
        _codex_event("response.failed", sequence_number=2, response=failed),
    ]


async def _iter_failure_events(
    body: ResponsesRequest,
    *,
    code: str,
    exc: BaseException,
) -> AsyncIterator[str]:
    for event in _failure_events(body, code=code, exc=exc):
        yield event


def _best_effort_wrapper(
    label: str,
    fn: Callable[..., Any],
    *,
    default: Any = None,
) -> Callable[..., Any]:
    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            logger.warning(
                f"[CODEX_V2_RUNTIME] ancillary {label} failed and was isolated: "
                f"{type(exc).__name__}"
            )
            return default

    setattr(_wrapped, "_uwa_codex_v2_guarded", True)
    return _wrapped


def install_codex_v2_runtime_hardening() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from app.api import codex_responses_v2 as v2

    for name, default in (
        ("write_trace_attempt", None),
        ("_store_responses_state", None),
        ("_persist_codex_history", None),
        ("bind_response_to_conversation", False),
    ):
        current = getattr(v2, name, None)
        if current is None or bool(getattr(current, "_uwa_codex_v2_guarded", False)):
            continue
        setattr(v2, name, _best_effort_wrapper(name, current, default=default))

    original_required_declared_tool = v2.required_declared_tool
    if not bool(getattr(original_required_declared_tool, "_uwa_codex_v2_guarded", False)):

        def _required_tool_once(body: ResponsesRequest) -> str:
            required = original_required_declared_tool(body)
            if not required:
                return ""

            declared = set(v2._declared_tool_names(body.tools))
            explicit_choice = v2._specific_tool_choice_name(body.tool_choice)
            if explicit_choice and explicit_choice in declared:
                return required

            if required in _completed_function_call_names(body.input):
                logger.info(
                    "[CODEX_V2_RUNTIME] required client tool already has a matching "
                    "function_call_output in the latest user turn; suppressing duplicate enforcement"
                )
                return ""
            return required

        setattr(_required_tool_once, "_uwa_codex_v2_guarded", True)
        v2.required_declared_tool = _required_tool_once

    original_browser_delta_request = v2._browser_delta_request
    if not bool(getattr(original_browser_delta_request, "_uwa_codex_v2_guarded", False)):

        def _tool_result_only_delta(body: ResponsesRequest) -> ResponsesRequest:
            base = original_browser_delta_request(body)
            trimmed = _tool_result_delta_body(base)
            if isinstance(body.input, list) and len(trimmed.input or []) < len(body.input):
                logger.info(
                    "[CODEX_V2_RUNTIME] trimmed reconstructed Responses history to "
                    "function_call_output delta for web-session reuse"
                )
            return trimmed

        setattr(_tool_result_only_delta, "_uwa_codex_v2_guarded", True)
        v2._browser_delta_request = _tool_result_only_delta

    original_prepare = v2._prepare_codex_web_turn
    if not bool(getattr(original_prepare, "_uwa_codex_v2_guarded", False)):

        def _prepare_with_call_id_affinity(body: ResponsesRequest):
            output_call_ids = _function_call_output_ids(body.input)
            mapped_response_id = _resolve_call_response(output_call_ids)
            if mapped_response_id:
                reasoning = v2.normalize_codex_reasoning(body.reasoning)
                try:
                    binding = v2.resolve_conversation_binding(
                        mapped_response_id,
                        model=v2.target_web_model(),
                        reasoning=reasoning,
                    )
                    if binding is not None and v2.ensure_chatgpt_conversation(binding.pathname):
                        state = v2.inspect_codex_web_mode_status(reasoning)
                        if bool(state.get("verified")):
                            try:
                                hydrated = v2._hydrate_codex_continuation(body)
                            except Exception as exc:
                                logger.warning(
                                    "[CODEX_V2_RUNTIME] full-history tool-result continuation "
                                    "could not hydrate locally; reusing call_id affinity with "
                                    f"delta state: {type(exc).__name__}"
                                )
                                hydrated = _degraded_reuse_state_body(body)
                            v2.install_codex_chatgpt_network_tuning()
                            logger.info(
                                "[CODEX_WEB_AFFINITY] reusing ChatGPT conversation from "
                                "function_call_output call_id (path redacted)"
                            )
                            return hydrated, True, binding.pathname, reasoning
                except Exception as exc:
                    logger.warning(
                        "[CODEX_V2_RUNTIME] call_id affinity fallback unavailable: "
                        f"{type(exc).__name__}"
                    )
            return original_prepare(body)

        setattr(_prepare_with_call_id_affinity, "_uwa_codex_v2_guarded", True)
        v2._prepare_codex_web_turn = _prepare_with_call_id_affinity

    original_required_tool_failed_events = v2._required_tool_failed_events
    if not bool(getattr(original_required_tool_failed_events, "_uwa_codex_v2_guarded", False)):

        def _compact_required_tool_failed_events(
            body: ResponsesRequest,
            required_tool: str,
        ) -> List[str]:
            return original_required_tool_failed_events(_compact_failure_body(body), required_tool)

        setattr(_compact_required_tool_failed_events, "_uwa_codex_v2_guarded", True)
        v2._required_tool_failed_events = _compact_required_tool_failed_events

    original_stream = v2._stream_codex_v2_attempt
    if not bool(getattr(original_stream, "_uwa_codex_v2_guarded", False)):

        async def _safe_stream(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
            buffered: List[str] = []
            try:
                async for chunk in original_stream(*args, **kwargs):
                    text = v2._chunk_text(chunk)
                    if v2._is_transport_comment(text):
                        yield text
                    else:
                        buffered.append(text)
            except Exception as exc:
                logger.exception(
                    "[CODEX_V2_RUNTIME] browser attempt stream crashed; converted to response.failed"
                )
                state_body = kwargs.get("state_body")
                if isinstance(state_body, ResponsesRequest):
                    for event in _failure_events(
                        state_body,
                        code="codex_v2_attempt_stream_failed",
                        exc=exc,
                    ):
                        yield event
                return

            response_id, call_ids = _response_and_call_ids_from_sse(buffered)
            if response_id and call_ids:
                _remember_call_response(call_ids, response_id)
                logger.info(
                    "[CODEX_V2_RUNTIME] remembered function call ids for same-web-conversation "
                    "tool-result continuation"
                )

            for text in buffered:
                yield text

        setattr(_safe_stream, "_uwa_codex_v2_guarded", True)
        v2._stream_codex_v2_attempt = _safe_stream

    original_attempt_response = v2._codex_web_attempt_response
    if not bool(getattr(original_attempt_response, "_uwa_codex_v2_guarded", False)):

        async def _safe_attempt_response(*args: Any, **kwargs: Any) -> StreamingResponse:
            try:
                return await original_attempt_response(*args, **kwargs)
            except Exception as exc:
                body = kwargs.get("body")
                request = kwargs.get("request")
                authenticated = kwargs.get("authenticated")
                if isinstance(body, ResponsesRequest) and str(body.previous_response_id or "").strip():
                    try:
                        reasoning = v2.normalize_codex_reasoning(body.reasoning)
                        binding = v2.resolve_conversation_binding(
                            body.previous_response_id,
                            model=v2.target_web_model(),
                            reasoning=reasoning,
                        )
                        if binding is not None and v2.ensure_chatgpt_conversation(binding.pathname):
                            state = v2.inspect_codex_web_mode_status(reasoning)
                            if bool(state.get("verified")):
                                logger.warning(
                                    "[CODEX_V2_RUNTIME] local continuation hydration failed; "
                                    "continuing the strict repair as a delta on the already-bound "
                                    f"ChatGPT conversation: {type(exc).__name__}"
                                )
                                fallback_state = _degraded_reuse_state_body(body)
                                v2.install_codex_chatgpt_network_tuning()
                                return StreamingResponse(
                                    v2._stream_codex_v2_attempt(
                                        request=request,
                                        state_body=fallback_state,
                                        browser_source_body=_model_copy(body),
                                        reuse_web_conversation=True,
                                        reused_path=binding.pathname,
                                        reasoning=reasoning,
                                        authenticated=authenticated,
                                    ),
                                    media_type="text/event-stream",
                                    headers=v2._stream_headers(),
                                )
                    except Exception as fallback_exc:
                        logger.warning(
                            "[CODEX_V2_RUNTIME] same-conversation degraded retry was unavailable: "
                            f"{type(fallback_exc).__name__}"
                        )

                logger.exception(
                    "[CODEX_V2_RUNTIME] browser turn preparation crashed; converted to response.failed"
                )
                if not isinstance(body, ResponsesRequest):
                    raise
                return StreamingResponse(
                    _iter_failure_events(
                        body,
                        code="codex_v2_turn_prepare_failed",
                        exc=exc,
                    ),
                    media_type="text/event-stream",
                    headers=v2._stream_headers(),
                )

        setattr(_safe_attempt_response, "_uwa_codex_v2_guarded", True)
        v2._codex_web_attempt_response = _safe_attempt_response

    original_strict_stream = v2._strict_required_tool_stream
    if not bool(getattr(original_strict_stream, "_uwa_codex_v2_guarded", False)):

        async def _safe_strict_required_tool_stream(
            *,
            request: Any,
            body: ResponsesRequest,
            authenticated: bool,
            required_tool: str,
            trace_id: str,
        ) -> AsyncIterator[str]:
            attempts = v2._strict_retry_max() + 1
            current_body = body

            for attempt in range(1, attempts + 1):
                response = await v2._codex_web_attempt_response(
                    request=request,
                    body=current_body,
                    authenticated=authenticated,
                )

                buffered: List[str] = []
                async for chunk in response.body_iterator:
                    text = v2._chunk_text(chunk)
                    if v2._is_transport_comment(text):
                        yield text
                    else:
                        buffered.append(text)

                response_summary = v2.summarize_responses_sse(buffered)
                names = response_summary.get("function_call_names") or []
                satisfied = required_tool in names
                response_summary["required_tool"] = required_tool
                response_summary["required_tool_satisfied"] = satisfied
                response_summary["strict_attempt"] = attempt

                request_summary = v2.summarize_responses_request(current_body, required_tool)
                request_summary["previous_response_id_present"] = bool(
                    str(current_body.previous_response_id or "").strip()
                )
                v2.write_trace_attempt(
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

                if str(response_summary.get("response_status") or "").strip().lower() == "failed":
                    logger.warning(
                        "[CODEX_V2_RUNTIME] strict repair attempt returned response.failed; "
                        "preserving the real terminal failure instead of rewriting it as a "
                        "missing-tool error"
                    )
                    for text in buffered:
                        yield text
                    return

                attempt_response_id = v2._response_id_from_sse(buffered)
                if attempt < attempts and attempt_response_id:
                    current_body = v2._clone_for_required_tool_retry(
                        body,
                        required_tool,
                        attempt=attempt + 1,
                        previous_response_id=attempt_response_id,
                    )
                    yield f": codex-v2-required-tool-retry attempt={attempt + 1}\n\n"
                    continue

                for text in v2._required_tool_failed_events(body, required_tool):
                    yield text
                return

        setattr(_safe_strict_required_tool_stream, "_uwa_codex_v2_guarded", True)
        v2._strict_required_tool_stream = _safe_strict_required_tool_stream

    _INSTALLED = True
    logger.info("[CODEX_V2_RUNTIME] streaming hardening installed")


__all__ = [
    "_compact_failure_body",
    "_completed_function_call_names",
    "_degraded_reuse_state_body",
    "_failure_events",
    "_function_call_output_ids",
    "_remember_call_response",
    "_resolve_call_response",
    "_response_and_call_ids_from_sse",
    "_tool_result_delta_body",
    "install_codex_v2_runtime_hardening",
]
