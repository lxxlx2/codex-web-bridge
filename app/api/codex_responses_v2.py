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
import unicodedata
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.chat import (
    ChatRequest,
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
    bind_history_to_conversation,
    bind_response_to_conversation,
    current_chatgpt_conversation_path,
    ensure_chatgpt_conversation,
    resolve_conversation_binding,
    resolve_history_conversation_binding,
    set_codex_workflow_reuse_hint,
)
from app.services.codex_wire_observability import (
    new_trace_id,
    summarize_responses_request,
    summarize_responses_sse,
    trace_status,
    write_trace_attempt,
)
from app.services.client_tool_policy import (
    _ACCEPTANCE_STATE_KEY,
    _acceptance_state_from_history,
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


def _current_user_texts(source: Any) -> List[str]:
    """Return user messages from the current turn, newest first.

    Codex Desktop appends an additional user-shaped environment/context item
    after the operator prompt. A plain "latest user message" lookup therefore
    sees that generated context instead of the operator action. Walk backwards
    through only the current user cluster and stop at the previous assistant
    turn so historical tool requirements cannot leak into a later request.
    """

    if isinstance(source, str):
        return [source] if source else []
    if not isinstance(source, list):
        return []

    texts: List[str] = []
    saw_user = False
    for item in reversed(source):
        if not isinstance(item, dict):
            continue

        role = str(item.get("role") or "").strip().lower()
        item_type = str(item.get("type") or "").strip().lower()
        is_user = role == "user" or (item_type == "message" and role == "user")

        if is_user:
            text = _content_text(item.get("content"))
            if text:
                texts.append(text)
            saw_user = True
            continue

        if saw_user and role == "assistant":
            break

    return texts


def _normalize_required_tool_text(value: str) -> str:
    """Normalize presentation-only escapes before required-tool detection.

    Codex Desktop can serialize tool-name text with markdown escapes or Unicode
    format characters even when the UI renders the canonical tool name. Keep
    this normalization detector-only so the original user request is preserved
    verbatim for repair prompts.
    """

    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\\_", "_")
    text = "".join(
        char
        for char in text
        if unicodedata.category(char) != "Cf"
    )

    aliases = {
        "exec_command": r"\bexec[\s_-]+command\b",
        "shell_command": r"\bshell[\s_-]+command\b",
        "local_shell": r"\blocal[\s_-]+shell\b",
        "apply_patch": r"\bapply[\s_-]+patch\b",
        "write_stdin": r"\bwrite[\s_-]+stdin\b",
    }
    for canonical, pattern in aliases.items():
        text = re.sub(pattern, canonical, text, flags=re.IGNORECASE)

    return text


def _required_tool_request_text(body: ResponsesRequest, required_tool: str) -> str:
    """Return the current-turn user text that explicitly requires the tool."""

    for user_text in _current_user_texts(body.input):
        detection_text = _normalize_required_tool_text(user_text)
        for pattern in _REQUIRED_TOOL_PATTERNS:
            match = pattern.search(detection_text)
            if not match:
                continue
            if str(match.group(1) or "").strip() == required_tool:
                return user_text
    return _latest_user_text(body.input)


def _input_has_compaction_checkpoint(source: Any) -> bool:
    if not isinstance(source, list):
        return False

    return any(
        isinstance(item, dict)
        and str(item.get("type") or "").strip().lower()
        in {"compaction", "compaction_summary"}
        for item in source
    )


def required_declared_tool(body: ResponsesRequest) -> str:
    declared = set(_declared_tool_names(body.tools))
    if not declared:
        return ""

    choice_name = _specific_tool_choice_name(body.tool_choice)
    if choice_name in declared:
        return choice_name

    for user_text in _current_user_texts(body.input):
        detection_text = _normalize_required_tool_text(user_text)
        for pattern in _REQUIRED_TOOL_PATTERNS:
            match = pattern.search(detection_text)
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
    fresh_replay: bool = False,
) -> ResponsesRequest:
    """Build an incremental repair turn that preserves the exact user action."""

    cloned = _model_copy(body)

    original_request = _required_tool_request_text(
        body,
        required_tool,
    ).strip()

    max_context_chars = 12000
    if len(original_request) > max_context_chars:
        half = max_context_chars // 2
        original_request = (
            original_request[:half]
            + "\n...[middle omitted for bounded repair context]...\n"
            + original_request[-half:]
        )

    repair = (
        "[Codex V2 Required Tool Contract]\n"
        f"The previous answer did not emit the required real client function "
        f"`{required_tool}`. "
        "Do not simulate command output and do not claim the declared tool is unavailable. "
        "The exact action requested by the user remains authoritative. "
        "Do not weaken, shorten, split, substitute, or partially probe that action. "
        "For exec-like tools, when the user specified a compound shell command, "
        "send the complete compound command in one real function call. "
        "A partial probe such as `pwd` alone does not satisfy a compound validation request. "
        f"Emit an actual `{required_tool}` function call using the declared schema, then wait "
        "for the client tool result. For exec-like tools omit `workdir` unless the user "
        f"explicitly requested another working directory. Repair attempt: {attempt}."
    )

    if original_request:
        repair += (
            "\n\nThe original user request for this repair is reproduced below. "
            "Follow its tool action exactly; this is not a new independent task.\n"
            "<original_user_request>\n"
            + original_request
            + "\n</original_user_request>"
        )

    cloned.instructions = None

    repair_item = {
        "role": "user",
        "content": repair,
    }

    if fresh_replay:
        cloned.previous_response_id = None

        if isinstance(cloned.input, list):
            cloned.input = [
                *cloned.input,
                repair_item,
            ]
        elif cloned.input in (None, ""):
            cloned.input = [repair_item]
        else:
            cloned.input = [
                cloned.input,
                repair_item,
            ]
    else:
        cloned.previous_response_id = (
            str(
                previous_response_id or ""
            ).strip()
            or None
        )
        cloned.input = [repair_item]

    cloned.tool_choice = {
        "type": "function",
        "name": required_tool,
    }

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



def _completed_response_has_no_output(
    response_status: str,
    response_obj: Dict[str, Any],
) -> bool:
    if str(response_status or "").strip().lower() != "completed":
        return False

    output = response_obj.get("output")
    return not isinstance(output, list) or not any(
        isinstance(item, dict)
        for item in output
    )


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



def _function_output_call_ids(source: Any) -> set[str]:
    """Return call ids carried by the current Responses tool-result delta."""

    if not isinstance(source, list):
        return set()

    call_ids: set[str] = set()
    for item in source:
        if not isinstance(item, dict):
            continue

        item_type = str(item.get("type") or "").strip().lower()
        if item_type not in {"function_call_output", "tool_result"}:
            continue

        call_id = str(
            item.get("call_id")
            or item.get("tool_call_id")
            or item.get("id")
            or ""
        ).strip()

        if call_id:
            call_ids.add(call_id)

    return call_ids


def _latest_compacted_continuation_context(
    messages: Any,
) -> str:
    """Return the newest compacted continuation text for internal delta metadata."""

    if not isinstance(messages, list):
        return ""

    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").strip().lower() != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str):
            text = content
        else:
            try:
                text = json.dumps(content, ensure_ascii=False)
            except Exception:
                text = str(content or "")
        if "[Compacted prior context]" in text:
            return text.strip()

    return ""


def _attach_compacted_context_to_generated_tool_fallbacks(
    request_body: ChatRequest,
    compacted_context: str,
) -> ChatRequest:
    """Carry compacted state as private metadata without replaying it to Web.

    Recursive compaction can leave the current affinity delta as either a
    generated user-shaped function-output fallback or a normal structured tool
    result with its matching assistant call. Both shapes need the same private
    continuation metadata for local policy decisions. The browser prompt
    serializer ignores this field.
    """

    value = str(compacted_context or "").strip()
    if not value:
        return request_body

    messages = (
        request_body.messages
        if isinstance(request_body.messages, list)
        else []
    )
    changed = False
    updated: List[Dict[str, Any]] = []

    for message in messages:
        if not isinstance(message, dict):
            continue
        next_message = dict(message)
        role = str(next_message.get("role") or "").strip().lower()
        if (
            next_message.get("_uwa_function_output_fallback") is True
            or role in {"tool", "function"}
        ):
            next_message["_uwa_compacted_continuation_context"] = value
            changed = True
        updated.append(next_message)

    if not changed:
        return request_body

    if hasattr(request_body, "model_copy"):
        return request_body.model_copy(
            update={"messages": updated}
        )

    return request_body.copy(
        update={"messages": updated}
    )


def _attach_acceptance_state_to_tool_delta(
    request_body: ChatRequest,
    history_messages: List[Dict[str, Any]],
) -> ChatRequest:
    """Keep proven synthetic progress available to local policy on affinity deltas.

    The browser prompt serializer reads role/content/tool_calls and ignores this
    private field. The snapshot contains only a known marker, result path and
    effect booleans; no command output or private continuation text is copied.
    """

    state = _acceptance_state_from_history(history_messages)
    if state is None:
        return request_body

    messages = (
        request_body.messages
        if isinstance(request_body.messages, list)
        else []
    )
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        if (
            role not in {"tool", "function"}
            and message.get("_uwa_function_output_fallback") is not True
        ):
            continue
        updated = [dict(item) if isinstance(item, dict) else item for item in messages]
        updated[index][_ACCEPTANCE_STATE_KEY] = state
        if hasattr(request_body, "model_copy"):
            return request_body.model_copy(update={"messages": updated})
        return request_body.copy(update={"messages": updated})
    return request_body


def _browser_delta_chat_request(
    state_chat_body: ChatRequest,
    browser_source_body: ResponsesRequest,
) -> ChatRequest:
    """Build an affinity delta while retaining minimal client-tool provenance.

    A lone Responses function_call_output cannot be represented faithfully as a
    Chat Completions tool message because its matching assistant function call
    has been removed together with previous_response_id. In that case recover
    only the matching assistant call plus the trailing tool-result delta from
    the hydrated state.

    This preserves tool-history semantics for validation and repair without
    replaying the complete conversation into the already-affined ChatGPT tab.
    """

    delta_body = _responses_request_to_chat_request(
        _browser_delta_request(browser_source_body),
        stream=False,
    )

    call_ids = _function_output_call_ids(browser_source_body.input)
    if not call_ids:
        return delta_body

    messages = (
        state_chat_body.messages
        if isinstance(state_chat_body.messages, list)
        else []
    )

    start_index: Optional[int] = None

    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").strip().lower() != "assistant":
            continue

        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue

        assistant_call_ids = {
            str(call.get("id") or "").strip()
            for call in tool_calls
            if isinstance(call, dict)
            and str(call.get("id") or "").strip()
        }

        if assistant_call_ids & call_ids:
            start_index = index
            break

    if start_index is None:
        compacted_delta = _attach_compacted_context_to_generated_tool_fallbacks(
            delta_body,
            _latest_compacted_continuation_context(
                messages
            ),
        )
        return _attach_acceptance_state_to_tool_delta(compacted_delta, messages)

    tail = messages[start_index:]

    matching_tool_result = any(
        isinstance(message, dict)
        and str(message.get("role") or "").strip().lower() == "tool"
        and str(message.get("tool_call_id") or "").strip() in call_ids
        for message in tail
    )

    if not matching_tool_result:
        return delta_body

    if hasattr(delta_body, "model_copy"):
        tail_body = delta_body.model_copy(
            update={"messages": [dict(message) for message in tail]}
        )
    else:
        tail_body = delta_body.copy(
            update={"messages": [dict(message) for message in tail]}
        )

    compacted_delta = _attach_compacted_context_to_generated_tool_fallbacks(
        tail_body,
        _latest_compacted_continuation_context(messages),
    )
    return _attach_acceptance_state_to_tool_delta(compacted_delta, messages)


def _browser_history_suffix_chat_request(
    state_chat_body: ChatRequest,
    prefix_count: int,
) -> ChatRequest:
    """Send only the unrepresented suffix of a matched full-history lineage."""

    messages = (
        state_chat_body.messages
        if isinstance(state_chat_body.messages, list)
        else []
    )
    count = max(0, int(prefix_count or 0))
    if count <= 0 or count >= len(messages):
        return state_chat_body

    suffix = [
        dict(message)
        for message in messages[count:]
        if isinstance(message, dict)
    ]

    if hasattr(state_chat_body, "model_copy"):
        suffix_body = state_chat_body.model_copy(
            update={"messages": suffix}
        )
    else:
        suffix_body = state_chat_body.copy(update={"messages": suffix})
    return _attach_acceptance_state_to_tool_delta(suffix_body, messages)


def _chat_history_after_response(
    request_messages: Any,
    chat_payload: Any,
) -> List[Dict[str, Any]]:
    messages = [
        dict(message)
        for message in request_messages
        if isinstance(message, dict)
    ] if isinstance(request_messages, list) else []

    choices = (
        chat_payload.get("choices")
        if isinstance(chat_payload, dict)
        and isinstance(chat_payload.get("choices"), list)
        else []
    )
    choice = (
        choices[0]
        if choices and isinstance(choices[0], dict)
        else {}
    )
    assistant = (
        choice.get("message")
        if isinstance(choice.get("message"), dict)
        else None
    )
    if assistant is not None:
        assistant_message = dict(assistant)
        assistant_message["role"] = "assistant"
        messages.append(assistant_message)

    return messages


def _prepare_codex_web_turn_with_history_affinity(
    body: ResponsesRequest,
) -> Tuple[ResponsesRequest, bool, str, str, int]:
    """Prepare browser state plus optional full-history prefix reuse metadata."""

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
    history_prefix_count = 0

    if binding is not None and ensure_chatgpt_conversation(binding.pathname):
        try:
            state = inspect_codex_web_mode_status(reasoning)
        except Exception:
            state = {"verified": False}
        if bool(state.get("verified")):
            reused = True
            reused_path = binding.pathname
            logger.info(
                "[CODEX_WEB_AFFINITY] reusing mapped ChatGPT conversation "
                "(path redacted)"
            )

    hydrated = _hydrate_codex_continuation(body)

    if not reused and not incoming_previous:
        state_chat_body = _responses_request_to_chat_request(
            hydrated,
            stream=False,
        )
        history_binding = resolve_history_conversation_binding(
            state_chat_body.messages,
            model=web_model,
            reasoning=reasoning,
        )
        if (
            history_binding is not None
            and ensure_chatgpt_conversation(history_binding.pathname)
        ):
            try:
                state = inspect_codex_web_mode_status(reasoning)
            except Exception:
                state = {"verified": False}
            if bool(state.get("verified")):
                reused = True
                reused_path = history_binding.pathname
                history_prefix_count = history_binding.message_count
                logger.info(
                    "[CODEX_WEB_AFFINITY] reusing hash-matched Codex full-history "
                    f"lineage prefix_messages={history_prefix_count} "
                    "(path redacted)"
                )

    if not reused:
        prepare_and_verify_codex_web_mode(body.reasoning)
        if incoming_previous:
            logger.info(
                "[CODEX_WEB_AFFINITY] mapping unavailable/unhealthy; "
                "falling back to fresh chat plus reconstructed history"
            )

    install_codex_chatgpt_network_tuning()
    return (
        hydrated,
        reused,
        reused_path,
        reasoning,
        history_prefix_count,
    )


def _prepare_codex_web_turn(body: ResponsesRequest) -> Tuple[ResponsesRequest, bool, str, str]:
    """Compatibility wrapper around the history-aware preparation path."""

    hydrated, reused, reused_path, reasoning, _ = (
        _prepare_codex_web_turn_with_history_affinity(body)
    )
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
    history_prefix_count: int = 0,
) -> AsyncIterator[str]:
    """Execute one Codex browser turn and emit the minimal Responses SSE contract."""

    response_id = _new_response_id()
    created_at = int(time.time())
    sequence = 1
    state_chat_body = _responses_request_to_chat_request(state_body, stream=False)
    if reuse_web_conversation and history_prefix_count > 0:
        browser_body = _browser_history_suffix_chat_request(
            state_chat_body,
            history_prefix_count,
        )
    elif reuse_web_conversation:
        browser_body = _browser_delta_chat_request(
            state_chat_body,
            browser_source_body,
        )
    else:
        browser_body = state_chat_body

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

    if _completed_response_has_no_output(response_status, completed):
        failed = _build_responses_object(
            state_body,
            payload,
            response_id=response_id,
            created_at=created_at,
            status="failed",
            error={
                "message": (
                    "ChatGPT Web completed without an assistant message "
                    "or client function call."
                ),
                "type": "execution_error",
                "code": "empty_completed_output",
            },
        )
        logger.warning(
            "[CODEX_RESPONSES_V2] rejected completed turn with empty output"
        )
        yield _codex_event(
            "response.failed",
            sequence_number=sequence,
            response=failed,
        )
        return

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
    completed_history = _chat_history_after_response(
        state_chat_body.messages,
        payload,
    )
    if completed_history:
        bind_history_to_conversation(
            completed_history,
            path,
            model=target_web_model(),
            reasoning=reasoning,
        )

    logger.info(
        "[CODEX_RESPONSES_V2] stream completed: "
        f"response_id={response_id} output_items={len(output)} "
        f"tool_names={tool_names or ['none']} status={response_status} "
        f"web_session_reused={reuse_web_conversation} "
        f"browser_input={'history_delta' if history_prefix_count > 0 else ('delta' if reuse_web_conversation else 'full')}"
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
    (
        state_body,
        reused,
        reused_path,
        reasoning,
        history_prefix_count,
    ) = _prepare_codex_web_turn_with_history_affinity(body)
    return StreamingResponse(
        _stream_codex_v2_attempt(
            request=request,
            state_body=state_body,
            browser_source_body=incoming,
            reuse_web_conversation=reused,
            reused_path=reused_path,
            reasoning=reasoning,
            authenticated=authenticated,
            history_prefix_count=history_prefix_count,
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
            fresh_replay = _input_has_compaction_checkpoint(
                body.input
            )

            current_body = _clone_for_required_tool_retry(
                body,
                required_tool,
                attempt=attempt + 1,
                previous_response_id=attempt_response_id,
                fresh_replay=fresh_replay,
            )

            if fresh_replay:
                logger.info(
                    "[CODEX_RESPONSES_V2] required-tool retry "
                    "uses fresh replay from compaction checkpoint"
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
