"""Codex SSE compatibility for long browser-backed Responses turns.

Two protocol details matter for long-context Codex runs:

* Codex applies its idle timeout around parsed SSE events. SSE comments keep the
  HTTP connection alive but are discarded by the eventsource parser, so a
  comment-only heartbeat does not reset that timer. Convert transport comments
  into ``response.in_progress`` events, which current Codex explicitly accepts
  and ignores while still counting as parsed SSE activity.
* ChatGPT Web does not currently expose OpenAI Responses token accounting to
  UWA. A zero usage object leaves Codex's session token usage at zero, which in
  turn prevents native auto-compaction from reaching its configured threshold.
  When (and only when) a completed response has no usable usage, provide a
  conservative local estimate. Real non-zero upstream usage always wins.

The estimator is deliberately metadata-only and process-local. It never logs or
persists prompts, tool arguments, response text, cookies, credentials, or local
workspace contents.
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from typing import Any, AsyncIterator, Callable

from app.core.config import get_logger


logger = get_logger("CODEX_STREAM_COMPAT")
_INSTALLED = False
_BYTES_PER_TOKEN = 3
_USAGE_TTL_SEC = 7200.0
_USAGE_MAX_ENTRIES = 4096
_USAGE_LOCK = threading.RLock()
_RESPONSE_TOTAL_TOKENS: "OrderedDict[str, tuple[float, int]]" = OrderedDict()
_HEARTBEAT_TYPE = "response.in_progress"


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump(exclude_none=True))
        except Exception:
            pass
    if hasattr(value, "dict"):
        try:
            return _jsonable(value.dict(exclude_none=True))
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return str(value)


def _estimate_tokens(value: Any) -> int:
    if value in (None, "", [], {}, ()):
        return 0
    try:
        encoded = json.dumps(
            _jsonable(value),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except Exception:
        encoded = str(value).encode("utf-8", errors="replace")
    if not encoded:
        return 0
    # Three UTF-8 bytes/token is intentionally conservative for mixed English,
    # code and CJK. Early compaction is safer than silently overrunning the
    # browser/model context when exact tokenizer usage is unavailable.
    return max(1, (len(encoded) + _BYTES_PER_TOKEN - 1) // _BYTES_PER_TOKEN)


def _prune_usage_locked(now: float | None = None) -> None:
    current = float(now if now is not None else time.time())
    cutoff = current - _USAGE_TTL_SEC
    expired = [key for key, value in _RESPONSE_TOTAL_TOKENS.items() if value[0] < cutoff]
    for key in expired:
        _RESPONSE_TOTAL_TOKENS.pop(key, None)
    while len(_RESPONSE_TOTAL_TOKENS) > _USAGE_MAX_ENTRIES:
        _RESPONSE_TOTAL_TOKENS.popitem(last=False)


def _remember_total(response_id: str, total_tokens: int) -> None:
    key = str(response_id or "").strip()
    if not key or total_tokens <= 0:
        return
    now = time.time()
    with _USAGE_LOCK:
        _prune_usage_locked(now)
        _RESPONSE_TOTAL_TOKENS[key] = (now, int(total_tokens))
        _RESPONSE_TOTAL_TOKENS.move_to_end(key)
        _prune_usage_locked(now)


def _previous_total(response_id: str) -> int:
    key = str(response_id or "").strip()
    if not key:
        return 0
    with _USAGE_LOCK:
        _prune_usage_locked()
        value = _RESPONSE_TOTAL_TOKENS.get(key)
        if value is None:
            return 0
        _RESPONSE_TOTAL_TOKENS.move_to_end(key)
        return int(value[1])


def _usage_total(usage: Any) -> int:
    if not isinstance(usage, dict):
        return 0
    total = usage.get("total_tokens")
    if isinstance(total, int) and total > 0:
        return total
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    return max(0, int(input_tokens or 0)) + max(0, int(output_tokens or 0))


def _transport_comment(text: str) -> bool:
    stripped = str(text or "").lstrip()
    return stripped.startswith(":") and "event:" not in stripped and "data:" not in stripped


def codex_heartbeat_event() -> str:
    payload = json.dumps({"type": _HEARTBEAT_TYPE}, separators=(",", ":"))
    return f"event: {_HEARTBEAT_TYPE}\ndata: {payload}\n\n"


def _is_codex_heartbeat(text: str) -> bool:
    return (
        f"event: {_HEARTBEAT_TYPE}" in str(text or "")
        and f'"type":"{_HEARTBEAT_TYPE}"' in str(text or "").replace(" ", "")
    )


def _body_previous_id(body: Any) -> str:
    return str(getattr(body, "previous_response_id", None) or "").strip()


def _body_input(body: Any) -> Any:
    return getattr(body, "input", None)


def _initial_request_estimate(body: Any, responses_to_chat: Callable[..., Any] | None) -> int:
    if body is None:
        return 0
    if responses_to_chat is not None:
        try:
            chat_body = responses_to_chat(body, stream=False)
            value = {
                "messages": getattr(chat_body, "messages", None),
                "tools": getattr(chat_body, "tools", None),
                "tool_choice": getattr(chat_body, "tool_choice", None),
            }
            estimate = _estimate_tokens(value)
            if estimate > 0:
                return estimate
        except Exception:
            pass
    return _estimate_tokens(body)


def _input_estimate(
    *,
    state_body: Any,
    source_body: Any,
    responses_to_chat: Callable[..., Any] | None,
) -> int:
    previous_id = _body_previous_id(state_body) or _body_previous_id(source_body)
    previous_total = _previous_total(previous_id)
    if previous_total > 0:
        # previous_total already represents the previous active context. Add only
        # the new turn's input; do not repeatedly charge fixed tool schemas.
        delta = _estimate_tokens(_body_input(source_body))
        return max(1, previous_total + delta)
    return max(1, _initial_request_estimate(state_body or source_body, responses_to_chat))


def _parse_sse_payload(text: str) -> tuple[str, dict[str, Any]] | None:
    event_name = ""
    data_lines: list[str] = []
    for line in str(text or "").replace("\r\n", "\n").splitlines():
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].lstrip())
    if not data_lines:
        return None
    try:
        payload = json.loads("\n".join(data_lines))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return event_name, payload


def _pack_sse(event_name: str, payload: dict[str, Any]) -> str:
    name = event_name or str(payload.get("type") or "message")
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def inject_estimated_usage(
    text: str,
    *,
    state_body: Any,
    source_body: Any,
    responses_to_chat: Callable[..., Any] | None = None,
) -> str:
    parsed = _parse_sse_payload(text)
    if parsed is None:
        return text
    event_name, payload = parsed
    if str(payload.get("type") or event_name) != "response.completed":
        return text
    response = payload.get("response")
    if not isinstance(response, dict):
        return text

    response_id = str(response.get("id") or "").strip()
    existing_total = _usage_total(response.get("usage"))
    if existing_total > 0:
        _remember_total(response_id, existing_total)
        return text

    input_tokens = _input_estimate(
        state_body=state_body,
        source_body=source_body,
        responses_to_chat=responses_to_chat,
    )
    output_tokens = _estimate_tokens(response.get("output"))
    total_tokens = input_tokens + output_tokens
    response["usage"] = {
        "input_tokens": input_tokens,
        "input_tokens_details": {
            "cached_tokens": 0,
            "cache_write_tokens": 0,
        },
        "output_tokens": output_tokens,
        "output_tokens_details": {
            "reasoning_tokens": 0,
        },
        "total_tokens": total_tokens,
    }
    _remember_total(response_id, total_tokens)
    logger.info(
        "[CODEX_USAGE] supplied conservative local usage estimate for auto-compaction: "
        f"input_tokens={input_tokens} output_tokens={output_tokens}"
    )
    return _pack_sse(event_name, payload)


def _wrap_stream(
    original: Callable[..., Any],
    *,
    body_resolver: Callable[[dict[str, Any]], tuple[Any, Any]],
    responses_to_chat: Callable[..., Any] | None,
) -> Callable[..., Any]:
    async def _wrapped(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
        state_body, source_body = body_resolver(kwargs)
        async for chunk in original(*args, **kwargs):
            text = chunk.decode("utf-8", "replace") if isinstance(chunk, bytes) else str(chunk or "")
            if _transport_comment(text):
                yield codex_heartbeat_event()
                continue
            yield inject_estimated_usage(
                text,
                state_body=state_body,
                source_body=source_body,
                responses_to_chat=responses_to_chat,
            )

    setattr(_wrapped, "_uwa_codex_stream_compat", True)
    return _wrapped


def install_codex_stream_compat() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from app.api import codex_responses as legacy
    from app.api import codex_responses_v2 as v2

    # The V2 runtime hardening layer intentionally lets transport comments flow
    # immediately while buffering other protocol events. Teach its downstream
    # strict-tool wrapper to treat our real heartbeat as transport-only too, so
    # the heartbeat is not re-buffered on required-tool turns.
    original_is_transport_comment = v2._is_transport_comment
    if not bool(getattr(original_is_transport_comment, "_uwa_codex_stream_compat", False)):
        def _transport_or_heartbeat(text: str) -> bool:
            return original_is_transport_comment(text) or _is_codex_heartbeat(text)

        setattr(_transport_or_heartbeat, "_uwa_codex_stream_compat", True)
        v2._is_transport_comment = _transport_or_heartbeat

    current_v2 = v2._stream_codex_v2_attempt
    if not bool(getattr(current_v2, "_uwa_codex_stream_compat", False)):
        v2._stream_codex_v2_attempt = _wrap_stream(
            current_v2,
            body_resolver=lambda kwargs: (
                kwargs.get("state_body"),
                kwargs.get("browser_source_body") or kwargs.get("state_body"),
            ),
            responses_to_chat=v2._responses_request_to_chat_request,
        )

    current_legacy = legacy._stream_codex_minimal_responses
    if not bool(getattr(current_legacy, "_uwa_codex_stream_compat", False)):
        legacy._stream_codex_minimal_responses = _wrap_stream(
            current_legacy,
            body_resolver=lambda kwargs: (kwargs.get("body"), kwargs.get("body")),
            responses_to_chat=legacy._responses_request_to_chat_request,
        )

    _INSTALLED = True


__all__ = [
    "codex_heartbeat_event",
    "inject_estimated_usage",
    "install_codex_stream_compat",
]
