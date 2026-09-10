"""Codex 0.153.4 remote-compaction V2 compatibility for UWA Responses.

Codex remote compaction V2 is an ordinary streamed Responses request whose input
ends in a request-only ``compaction_trigger`` item.  The response must contain
exactly one ``type=compaction`` output item.  ChatGPT Web cannot consume or emit
that opaque item directly, so this adapter:

* strips the request-only trigger before browser inference;
* asks ChatGPT Web for a bounded no-tools durable-thread summary;
* wraps the summary in a versioned UWA-owned opaque envelope carried in the
  upstream ``encrypted_content`` field;
* decodes only UWA-owned envelopes back into model-visible assistant context on
  later ordinary Responses turns.

The UWA envelope is integrity-checked transport state, not OpenAI encryption.
No envelope or summary body is logged here.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import hmac
import json
import time
from typing import Any, AsyncIterator, Dict, Tuple

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.api.chat import ResponsesRequest
from app.core.config import get_logger


logger = get_logger("CODEX_REMOTE_COMPACTION_V2")
_INSTALLED = False

_TRIGGER_TYPE = "compaction_trigger"
_COMPACTION_TYPES = {"compaction", "compaction_summary"}
_UNSUPPORTED_COMPACTION_TYPES = {"context_compaction"}
_ENVELOPE_PREFIX = "uwa-codex-compact-v1."
_ENVELOPE_KIND = "uwa_codex_compaction"
_ENVELOPE_VERSION = 1
_MAX_SUMMARY_BYTES = 64 * 1024
_MAX_ENVELOPE_BYTES = 96 * 1024
_BYTES_PER_TOKEN = 3

_COMPACTION_INSTRUCTIONS = """[Codex Remote Compaction V2]
Create a compact replacement-history summary for a long-running coding thread.
Preserve facts needed to continue work correctly: user goals, explicit constraints,
important decisions, repository/file paths, edits already made, tests and their
results, failures and diagnoses, unresolved work, and the next intended actions.
Explicitly distinguish completed historical requests from the current active goal.
Never present a completed old user request as a current actionable instruction; only
unresolved work and the current next actions may remain actionable.
Do not invent facts. Do not call tools. Do not output function calls. Do not add
ceremonial prose. Return only the concise continuation summary for the next model
turn. Prefer durable facts over transient chatter or verbose command output.
"""


class RemoteCompactionV2ProtocolError(ValueError):
    """Fail-closed protocol/envelope validation error."""


def _model_copy(body: ResponsesRequest) -> ResponsesRequest:
    if hasattr(body, "model_copy"):
        return body.model_copy(deep=True)
    return body.copy(deep=True)


def _item_type(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    return str(item.get("type") or "").strip().lower()


def _trigger_indexes(source: Any) -> list[int]:
    if not isinstance(source, list):
        return []
    return [index for index, item in enumerate(source) if _item_type(item) == _TRIGGER_TYPE]


def has_remote_compaction_trigger(source: Any) -> bool:
    """Return True only after validating the exact trailing-trigger shape."""

    indexes = _trigger_indexes(source)
    if not indexes:
        return False
    if not isinstance(source, list) or len(indexes) != 1 or indexes[0] != len(source) - 1:
        raise RemoteCompactionV2ProtocolError(
            "remote compaction requires exactly one trailing compaction_trigger"
        )
    trigger = source[indexes[0]]
    if not isinstance(trigger, dict) or set(trigger) != {"type"}:
        raise RemoteCompactionV2ProtocolError(
            "compaction_trigger must contain only its type discriminator"
        )
    if len(source) == 1:
        raise RemoteCompactionV2ProtocolError("compaction_trigger has no history to compact")
    return True


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    try:
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))
    except Exception as exc:
        raise RemoteCompactionV2ProtocolError("invalid UWA compaction envelope encoding") from exc


def encode_compaction_envelope(summary: str) -> str:
    text = str(summary or "").strip()
    raw_summary = text.encode("utf-8")
    if not raw_summary:
        raise RemoteCompactionV2ProtocolError("compaction summary is empty")
    if len(raw_summary) > _MAX_SUMMARY_BYTES:
        raise RemoteCompactionV2ProtocolError("compaction summary exceeds UWA bound")

    payload = {
        "kind": _ENVELOPE_KIND,
        "summary": text,
        "v": _ENVELOPE_VERSION,
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    envelope = f"{_ENVELOPE_PREFIX}{_b64url_encode(raw)}.{digest}"
    if len(envelope.encode("utf-8")) > _MAX_ENVELOPE_BYTES:
        raise RemoteCompactionV2ProtocolError("compaction envelope exceeds UWA bound")
    return envelope


def decode_compaction_envelope(envelope: str) -> str:
    value = str(envelope or "")
    if not value.startswith(_ENVELOPE_PREFIX):
        raise RemoteCompactionV2ProtocolError("foreign compaction envelope")
    if len(value.encode("utf-8")) > _MAX_ENVELOPE_BYTES:
        raise RemoteCompactionV2ProtocolError("compaction envelope exceeds UWA bound")

    encoded_and_digest = value[len(_ENVELOPE_PREFIX) :]
    try:
        encoded, digest = encoded_and_digest.rsplit(".", 1)
    except ValueError as exc:
        raise RemoteCompactionV2ProtocolError("invalid UWA compaction envelope framing") from exc
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise RemoteCompactionV2ProtocolError("invalid UWA compaction envelope digest")

    raw = _b64url_decode(encoded)
    if len(raw) > _MAX_SUMMARY_BYTES + 4096:
        raise RemoteCompactionV2ProtocolError("decoded compaction envelope exceeds UWA bound")
    actual = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual, digest):
        raise RemoteCompactionV2ProtocolError("UWA compaction envelope integrity check failed")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RemoteCompactionV2ProtocolError("invalid UWA compaction envelope payload") from exc
    if not isinstance(payload, dict) or set(payload) != {"kind", "summary", "v"}:
        raise RemoteCompactionV2ProtocolError("invalid UWA compaction envelope schema")
    if payload.get("kind") != _ENVELOPE_KIND or payload.get("v") != _ENVELOPE_VERSION:
        raise RemoteCompactionV2ProtocolError("unsupported UWA compaction envelope version")

    summary = str(payload.get("summary") or "").strip()
    encoded_summary = summary.encode("utf-8")
    if not encoded_summary or len(encoded_summary) > _MAX_SUMMARY_BYTES:
        raise RemoteCompactionV2ProtocolError("invalid UWA compaction summary bound")
    return summary


def _compaction_message(summary: str) -> Dict[str, Any]:
    return {
        "type": "message",
        "role": "assistant",
        "content": [
            {
                "type": "output_text",
                "text": "[Compacted prior context]\n" + summary,
            }
        ],
    }


def rewrite_uwa_compaction_history(source: Any) -> Any:
    """Replace one valid UWA Compaction item with model-visible summary context."""

    if not isinstance(source, list):
        return source
    rewritten: list[Any] = []
    seen = 0
    for item in source:
        item_type = _item_type(item)
        if item_type in _UNSUPPORTED_COMPACTION_TYPES:
            raise RemoteCompactionV2ProtocolError(
                f"unsupported compaction item type: {item_type}"
            )
        if item_type not in _COMPACTION_TYPES:
            rewritten.append(copy.deepcopy(item))
            continue
        seen += 1
        if seen > 1:
            raise RemoteCompactionV2ProtocolError("multiple compaction items are not supported")
        if not isinstance(item, dict):
            raise RemoteCompactionV2ProtocolError("invalid compaction item")
        summary = decode_compaction_envelope(str(item.get("encrypted_content") or ""))
        rewritten.append(_compaction_message(summary))
    return rewritten


def normalize_history_body(body: ResponsesRequest) -> ResponsesRequest:
    cloned = _model_copy(body)
    cloned.input = rewrite_uwa_compaction_history(cloned.input)
    return cloned


def build_compaction_backing_body(body: ResponsesRequest) -> ResponsesRequest:
    cloned = normalize_history_body(body)
    if not has_remote_compaction_trigger(cloned.input):
        raise RemoteCompactionV2ProtocolError("missing remote compaction trigger")

    assert isinstance(cloned.input, list)
    cloned.input = cloned.input[:-1]
    original_instructions = str(cloned.instructions or "").strip()
    cloned.instructions = _COMPACTION_INSTRUCTIONS
    if original_instructions:
        cloned.instructions += (
            "\nActive thread instructions follow for context. Preserve only constraints "
            "needed for continuation; do not quote them wholesale.\n\n"
            + original_instructions
        )
    # Codex sends full prompt history for remote V2. Do not combine it with a
    # process-local previous_response_id snapshot and do not expose client tools.
    cloned.previous_response_id = None
    cloned.tools = None
    cloned.tool_choice = "none"
    cloned.parallel_tool_calls = False
    cloned.stream = False
    cloned.store = False
    cloned.max_output_tokens = 12000
    return cloned


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        return "\n".join(_content_text(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return "\n".join(_content_text(item) for item in value)
    return ""


def extract_backing_summary(payload: Dict[str, Any]) -> str:
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise RemoteCompactionV2ProtocolError("compaction backing response has invalid choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise RemoteCompactionV2ProtocolError("compaction backing response has no assistant message")
    if message.get("tool_calls"):
        raise RemoteCompactionV2ProtocolError("compaction backing response attempted a tool call")
    summary = _content_text(message.get("content")).strip()
    if not summary:
        raise RemoteCompactionV2ProtocolError("compaction backing response has no summary")
    # Encoding validates the same byte bound used on the wire.
    if len(summary.encode("utf-8")) > _MAX_SUMMARY_BYTES:
        raise RemoteCompactionV2ProtocolError("compaction backing summary exceeds UWA bound")
    return summary


def _estimate_tokens(value: Any) -> int:
    try:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    except Exception:
        raw = str(value).encode("utf-8", errors="replace")
    return max(1, (len(raw) + _BYTES_PER_TOKEN - 1) // _BYTES_PER_TOKEN)


def compaction_usage(backing_body: ResponsesRequest, summary: str) -> Dict[str, Any]:
    input_tokens = _estimate_tokens(
        {
            "instructions": backing_body.instructions,
            "input": backing_body.input,
        }
    )
    output_tokens = _estimate_tokens(summary)
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": input_tokens + output_tokens,
    }


def _protocol_http_error(exc: RemoteCompactionV2ProtocolError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


async def _stream_remote_compaction_v2(
    *,
    v2: Any,
    request: Any,
    body: ResponsesRequest,
    authenticated: bool,
) -> AsyncIterator[str]:
    backing_body = build_compaction_backing_body(body)
    response_id = v2._new_response_id()
    created_at = int(time.time())
    sequence = 1

    in_progress = v2._build_responses_object(
        body,
        {"choices": [], "usage": {}},
        response_id=response_id,
        created_at=created_at,
        status="in_progress",
        error=None,
    )
    yield v2._codex_event(
        "response.created",
        sequence_number=sequence,
        response=in_progress,
    )
    sequence += 1

    # Always compact from a fresh verified composer. Remote V2 supplies its own
    # full history and should not append that history to an affinity-reused chat.
    v2.prepare_and_verify_codex_web_mode(backing_body.reasoning)
    v2.install_codex_chatgpt_network_tuning()
    chat_body = v2._responses_request_to_chat_request(backing_body, stream=False)

    task = asyncio.create_task(
        v2._run_chat_completion_final(
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
                    timeout=v2._CODEX_SSE_KEEPALIVE_SEC,
                )
            except asyncio.TimeoutError:
                if await request.is_disconnected():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    return
                # Installed stream compatibility turns this transport comment into a
                # parseable response.in_progress heartbeat for Codex's idle timer.
                yield ": keepalive\n\n"

        status_code, payload = task.result()
        if status_code >= 400 or not isinstance(payload, dict) or "error" in payload:
            raise RemoteCompactionV2ProtocolError("compaction backing request failed")

        summary = extract_backing_summary(payload)
        envelope = encode_compaction_envelope(summary)
        item = {
            "type": "compaction",
            "encrypted_content": envelope,
        }
        usage = compaction_usage(backing_body, summary)

        yield v2._codex_event(
            "response.output_item.done",
            sequence_number=sequence,
            output_index=0,
            item=item,
        )
        sequence += 1

        completed = v2._build_responses_object(
            body,
            {"choices": [], "usage": usage},
            response_id=response_id,
            created_at=created_at,
            status="completed",
            error=None,
        )
        completed["output"] = [item]
        completed["usage"] = usage
        completed["status"] = "completed"

        logger.info(
            "[CODEX_REMOTE_COMPACTION_V2] completed remote compact: "
            f"summary_bytes={len(summary.encode('utf-8'))} "
            f"envelope_bytes={len(envelope.encode('utf-8'))} output_items=1"
        )
        yield v2._codex_event(
            "response.completed",
            sequence_number=sequence,
            response=completed,
        )
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


def _normalize_stream_kwargs(kwargs: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    updated = dict(kwargs)
    source_body = updated.get("browser_source_body")
    state_body = updated.get("state_body")

    trigger = False
    if isinstance(source_body, ResponsesRequest):
        trigger = has_remote_compaction_trigger(source_body.input)
    elif isinstance(state_body, ResponsesRequest):
        trigger = has_remote_compaction_trigger(state_body.input)

    if trigger:
        return updated, True

    if isinstance(state_body, ResponsesRequest):
        updated["state_body"] = normalize_history_body(state_body)
    if isinstance(source_body, ResponsesRequest):
        updated["browser_source_body"] = normalize_history_body(source_body)
    return updated, False


def install_codex_remote_compaction_v2() -> None:
    """Install before runtime-hardening/stream-compat so their guards wrap us."""

    global _INSTALLED
    if _INSTALLED:
        return

    from app.api import codex_responses_v2 as v2

    original_required = v2.required_declared_tool
    if not bool(getattr(original_required, "_uwa_remote_compaction_v2", False)):

        def _required_tool_except_compaction(body: ResponsesRequest) -> str:
            try:
                if has_remote_compaction_trigger(body.input):
                    return ""
            except RemoteCompactionV2ProtocolError as exc:
                raise _protocol_http_error(exc) from exc
            return original_required(body)

        setattr(_required_tool_except_compaction, "_uwa_remote_compaction_v2", True)
        v2.required_declared_tool = _required_tool_except_compaction

    original_stream = v2._stream_codex_v2_attempt
    if not bool(getattr(original_stream, "_uwa_remote_compaction_v2", False)):

        async def _stream_with_remote_compaction(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
            normalized_kwargs, is_compaction = _normalize_stream_kwargs(kwargs)
            if is_compaction:
                source = normalized_kwargs.get("browser_source_body")
                state = normalized_kwargs.get("state_body")
                body = source if isinstance(source, ResponsesRequest) else state
                if not isinstance(body, ResponsesRequest):
                    raise RemoteCompactionV2ProtocolError("missing Responses body for compaction")
                async for chunk in _stream_remote_compaction_v2(
                    v2=v2,
                    request=normalized_kwargs.get("request"),
                    body=body,
                    authenticated=bool(normalized_kwargs.get("authenticated")),
                ):
                    yield chunk
                return

            async for chunk in original_stream(*args, **normalized_kwargs):
                yield chunk

        setattr(_stream_with_remote_compaction, "_uwa_remote_compaction_v2", True)
        v2._stream_codex_v2_attempt = _stream_with_remote_compaction

    # `codex_responses_v2` delegates requests without a non-empty tools list to
    # this imported fallback symbol. Wrap it too so post-compaction no-tool turns
    # decode UWA envelopes, and a future no-tool remote-compaction request still
    # follows the V2 protocol instead of leaking compaction_trigger downstream.
    original_aware = v2.codex_aware_responses
    if not bool(getattr(original_aware, "_uwa_remote_compaction_v2", False)):

        async def _aware_with_remote_compaction(*args: Any, **kwargs: Any):
            body = kwargs.get("body")
            if not isinstance(body, ResponsesRequest):
                return await original_aware(*args, **kwargs)
            try:
                if has_remote_compaction_trigger(body.input):
                    return StreamingResponse(
                        _stream_remote_compaction_v2(
                            v2=v2,
                            request=kwargs.get("request"),
                            body=body,
                            authenticated=bool(kwargs.get("authenticated")),
                        ),
                        media_type="text/event-stream",
                        headers=v2._stream_headers(),
                    )
                normalized = normalize_history_body(body)
            except RemoteCompactionV2ProtocolError as exc:
                raise _protocol_http_error(exc) from exc
            forwarded = dict(kwargs)
            forwarded["body"] = normalized
            return await original_aware(*args, **forwarded)

        setattr(_aware_with_remote_compaction, "_uwa_remote_compaction_v2", True)
        v2.codex_aware_responses = _aware_with_remote_compaction

    _INSTALLED = True
    logger.info("[CODEX_REMOTE_COMPACTION_V2] compatibility installed")
