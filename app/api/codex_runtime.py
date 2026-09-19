"""Standalone Codex Responses protocol/runtime seam.

This module owns the OpenAI Responses request model, in-process continuation
state and the narrow request/response conversion helpers used by the Codex
bridge. It intentionally avoids importing the large legacy ``app.api.chat``
module at import time.

The browser execution worker is still delegated lazily to the validated legacy
chat runtime while S2 extraction continues. Keeping that import inside the
worker boundary lets the standalone application start with a Codex-only import
graph and gives the next extraction step one explicit seam to replace.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.deps import verify_service_auth
from app.core.config import get_logger


logger = get_logger("API.CODEX_RUNTIME")
RESPONSES_STATE_MAX_ENTRIES = 1024
RESPONSES_STATE_TTL_SEC = 3600.0

_responses_state_lock = threading.RLock()
_responses_state_by_id: "OrderedDict[str, tuple[float, str]]" = OrderedDict()


class ChatRequest(BaseModel):
    model: str = Field(default="未知")
    messages: list = Field(...)
    stream: Optional[bool] = Field(default=False)
    temperature: Optional[float] = Field(default=0.7, ge=0, le=2)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    n: Optional[int] = Field(default=1, ge=1)
    response_format: Optional[dict] = Field(default=None)
    stop: Optional[Any] = Field(default=None)
    tools: Optional[list] = Field(default=None)
    tool_choice: Optional[Any] = Field(default=None)
    parallel_tool_calls: Optional[bool] = Field(default=None)
    functions: Optional[list] = Field(default=None)
    function_call: Optional[Any] = Field(default=None)
    preset_name: Optional[str] = Field(default=None)
    stream_options: Optional[dict] = Field(default=None)


class ResponsesRequest(BaseModel):
    """Responses API request model consumed by Codex Desktop/CLI."""

    model: str = Field(default="未知")
    input: Optional[Any] = Field(default="")
    instructions: Optional[str] = Field(default=None)
    stream: Optional[bool] = Field(default=False)
    temperature: Optional[float] = Field(default=1.0, ge=0, le=2)
    max_output_tokens: Optional[int] = Field(default=None, ge=1)
    tools: Optional[list] = Field(default=None)
    tool_choice: Optional[Any] = Field(default=None)
    parallel_tool_calls: Optional[bool] = Field(default=None)
    text: Optional[dict] = Field(default=None)
    metadata: Optional[dict] = Field(default=None)
    prompt: Optional[Any] = Field(default=None)
    previous_response_id: Optional[str] = Field(default=None)
    reasoning: Optional[dict] = Field(default=None)
    store: Optional[bool] = Field(default=None)
    top_p: Optional[float] = Field(default=None, ge=0, le=1)
    truncation: Optional[str] = Field(default=None)
    user: Optional[str] = Field(default=None)
    stop: Optional[Any] = Field(default=None)

    model_config = {"extra": "allow"}


async def verify_auth(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> bool:
    return await verify_service_auth(
        authorization=authorization,
        x_api_key=x_api_key,
    )


def _new_response_id() -> str:
    return f"resp_{int(time.time() * 1000)}_{uuid.uuid4().hex[:10]}"


def _new_response_item_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _prune_responses_state_locked(now: Optional[float] = None) -> None:
    cutoff = float(now if now is not None else time.time()) - RESPONSES_STATE_TTL_SEC
    expired_ids = [
        response_id
        for response_id, (stored_at, _messages) in _responses_state_by_id.items()
        if stored_at < cutoff
    ]
    for response_id in expired_ids:
        _responses_state_by_id.pop(response_id, None)
    while len(_responses_state_by_id) > RESPONSES_STATE_MAX_ENTRIES:
        _responses_state_by_id.popitem(last=False)


def _load_responses_state(previous_response_id: Optional[str]) -> List[Dict[str, Any]]:
    response_id = str(previous_response_id or "").strip()
    if not response_id:
        return []
    with _responses_state_lock:
        _prune_responses_state_locked()
        entry = _responses_state_by_id.get(response_id)
        if entry is None:
            raise HTTPException(
                status_code=404,
                detail=f"previous_response_id not found or expired: {response_id}",
            )
        _responses_state_by_id.move_to_end(response_id)
        serialized = entry[1]
    return json.loads(serialized)


def _store_responses_state(
    response_id: str,
    request_messages: List[Dict[str, Any]],
    chat_payload: Dict[str, Any],
    *,
    enabled: bool,
) -> None:
    if not enabled:
        return

    choices = chat_payload.get("choices") if isinstance(chat_payload, dict) else None
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    assistant = choice.get("message") if isinstance(choice.get("message"), dict) else None
    if assistant is None:
        return

    history = list(request_messages or [])
    assistant_message = dict(assistant)
    assistant_message["role"] = "assistant"
    history.append(assistant_message)

    key = str(response_id or "").strip()
    if not key:
        return
    try:
        serialized = json.dumps(history, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        logger.warning(f"responses history serialization failed; skipping state: {exc}")
        return

    with _responses_state_lock:
        _prune_responses_state_locked()
        _responses_state_by_id[key] = (time.time(), serialized)
        _responses_state_by_id.move_to_end(key)
        _prune_responses_state_locked()


def _normalize_response_tool_choice(value: Any) -> Any:
    if isinstance(value, dict):
        value_type = str(value.get("type") or "").strip().lower()
        if value_type == "function":
            function_block = value.get("function") if isinstance(value.get("function"), dict) else {}
            name = str(function_block.get("name") or value.get("name") or "").strip()
            if name:
                return {"type": "function", "function": {"name": name}}
    return value


def _normalize_responses_tools(tools: Any) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(tools, list):
        return None

    normalized: List[Dict[str, Any]] = []
    for item in tools:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").strip().lower() != "function":
            continue

        if isinstance(item.get("function"), dict):
            fn = item["function"]
            name = str(fn.get("name") or "").strip()
            if not name:
                continue
            normalized.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": str(fn.get("description") or "").strip(),
                        "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
                    },
                }
            )
            continue

        name = str(item.get("name") or "").strip()
        if not name:
            continue
        normalized.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(item.get("description") or "").strip(),
                    "parameters": item.get("parameters", {"type": "object", "properties": {}}),
                },
            }
        )

    return normalized or None


def _normalize_responses_text_format(text_config: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(text_config, dict):
        return None
    format_config = text_config.get("format")
    if not isinstance(format_config, dict):
        return None

    format_type = str(format_config.get("type") or "text").strip().lower()
    if format_type == "json_schema":
        if isinstance(format_config.get("json_schema"), dict):
            payload = format_config["json_schema"]
        else:
            payload: Dict[str, Any] = {}
            if "name" in format_config:
                payload["name"] = format_config.get("name")
            if "schema" in format_config:
                payload["schema"] = format_config.get("schema")
            if "strict" in format_config:
                payload["strict"] = format_config.get("strict")
        return {"type": "json_schema", "json_schema": payload}
    if format_type == "json_object":
        return {"type": "json_object"}
    return {"type": format_type}


def _normalize_response_message_content(content: Any) -> Any:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return _normalize_response_message_content([content])
    if not isinstance(content, list):
        return str(content)

    normalized_parts: List[Dict[str, Any]] = []
    leading_text_parts: List[str] = []

    for part in content:
        if isinstance(part, str):
            if part:
                leading_text_parts.append(part)
            continue
        if not isinstance(part, dict):
            text = str(part or "")
            if text:
                leading_text_parts.append(text)
            continue

        part_type = str(part.get("type") or "").strip().lower()
        if part_type in {"input_text", "output_text", "text"}:
            text = str(part.get("text") or "")
            if not text:
                continue
            if normalized_parts:
                normalized_parts.append({"type": "text", "text": text})
            else:
                leading_text_parts.append(text)
            continue

        if part_type in {"input_image", "image_url", "output_image"}:
            image_value = part.get("image_url")
            if isinstance(image_value, dict):
                image_url = str(image_value.get("url") or "").strip()
                detail = str(image_value.get("detail") or "").strip()
            else:
                image_url = str(image_value or part.get("url") or "").strip()
                detail = str(part.get("detail") or "").strip()
            if not image_url:
                continue
            image_payload: Dict[str, Any] = {"url": image_url}
            if detail:
                image_payload["detail"] = detail
            normalized_parts.append({"type": "image_url", "image_url": image_payload})
            continue

        if part_type in {
            "input_audio",
            "audio_url",
            "output_audio",
            "input_video",
            "video_url",
            "output_video",
        }:
            if part_type in {"input_audio", "audio_url", "output_audio"}:
                media_value = part.get("audio_url") or part.get("input_audio") or part.get("url") or ""
                media_label = "audio"
            else:
                media_value = part.get("video_url") or part.get("url") or ""
                media_label = "video"
            media_url = str(
                media_value.get("url") if isinstance(media_value, dict) else media_value
            ).strip()
            if media_url:
                media_text = f"[{media_label}]({media_url})"
                if normalized_parts:
                    normalized_parts.append({"type": "text", "text": media_text})
                else:
                    leading_text_parts.append(media_text)
            continue

        fallback_value = part.get("text")
        if fallback_value is None:
            fallback_value = part.get("output")
        if fallback_value is None:
            fallback_value = part.get("content")
        if fallback_value is None:
            fallback = json.dumps(part, ensure_ascii=False)
        elif isinstance(fallback_value, (dict, list)):
            fallback = json.dumps(fallback_value, ensure_ascii=False)
        else:
            fallback = str(fallback_value).strip()
        if fallback:
            if normalized_parts:
                normalized_parts.append({"type": "text", "text": fallback})
            else:
                leading_text_parts.append(fallback)

    joined_text = "\n".join(part for part in leading_text_parts if part)
    if not normalized_parts:
        return joined_text
    if joined_text:
        normalized_parts.insert(0, {"type": "text", "text": joined_text})
    return normalized_parts


def _normalize_response_input_role(role: Any) -> str:
    normalized_role = str(role or "user").strip().lower()
    if normalized_role == "developer":
        return "system"
    if normalized_role in {"system", "user", "assistant", "tool"}:
        return normalized_role
    return "user"


def _normalize_response_tool_output_content(content: Any) -> Any:
    normalized = _normalize_response_message_content(content)
    return "" if normalized in ("", None) else normalized


def _responses_tool_output_can_follow_openai(
    messages: List[Dict[str, Any]],
    tool_call_id: str,
) -> bool:
    if not tool_call_id:
        return False
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        if role == "tool":
            continue
        if role != "assistant":
            return False
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list) or not tool_calls:
            return False
        return any(
            isinstance(item, dict) and str(item.get("id") or "").strip() == tool_call_id
            for item in tool_calls
        )
    return False


def _responses_tool_output_fallback_content(item: Dict[str, Any], output: Any) -> Any:
    call_id = str(item.get("call_id") or item.get("tool_call_id") or item.get("id") or "").strip()
    name = str(item.get("name") or "").strip()
    header = "[Function Call Output"
    if name:
        header += f": {name}"
    if call_id:
        header += f" ({call_id})"
    header += "]"
    if isinstance(output, list):
        return [{"type": "text", "text": f"{header}\n"}] + output
    if isinstance(output, dict):
        output = json.dumps(output, ensure_ascii=False)
    return f"{header}\n{str(output or '')}".strip()


def _response_function_call_to_tool_call(item: Dict[str, Any]) -> Dict[str, Any]:
    arguments = item.get("arguments")
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments if arguments is not None else {}, ensure_ascii=False)
    return {
        "id": str(item.get("call_id") or item.get("id") or _new_response_item_id("call")).strip(),
        "type": "function",
        "function": {
            "name": str(item.get("name") or "").strip(),
            "arguments": arguments,
        },
    }


def _normalize_chat_style_tool_calls(tool_calls: Any) -> Optional[List[Any]]:
    if not isinstance(tool_calls, list):
        return None
    normalized: List[Any] = []
    for item in tool_calls:
        if not isinstance(item, dict):
            normalized.append(item)
            continue
        next_item = dict(item)
        function_data = next_item.get("function")
        if isinstance(function_data, dict):
            next_function = dict(function_data)
            arguments = next_function.get("arguments")
            if not isinstance(arguments, str):
                next_function["arguments"] = json.dumps(
                    arguments if arguments is not None else {},
                    ensure_ascii=False,
                )
            next_item["function"] = next_function
        normalized.append(next_item)
    return normalized


def _append_response_input_item(messages: List[Dict[str, Any]], item: Any) -> None:
    if item is None:
        return
    if isinstance(item, str):
        if item:
            messages.append({"role": "user", "content": item})
        return
    if not isinstance(item, dict):
        text = str(item)
        if text:
            messages.append({"role": "user", "content": text})
        return

    role = str(item.get("role") or "").strip().lower()
    item_type = str(item.get("type") or "").strip().lower()
    if role or item_type == "message":
        normalized_role = _normalize_response_input_role(role)
        content = item.get("content")
        if content is None and "text" in item:
            content = item.get("text")
        message_payload: Dict[str, Any] = {
            "role": normalized_role,
            "content": _normalize_response_message_content(content),
        }
        if normalized_role == "assistant":
            tool_calls = _normalize_chat_style_tool_calls(item.get("tool_calls"))
            if tool_calls is not None:
                message_payload["tool_calls"] = tool_calls
        if normalized_role == "tool":
            tool_call_id = str(
                item.get("tool_call_id") or item.get("call_id") or item.get("id") or ""
            ).strip()
            if tool_call_id:
                message_payload["tool_call_id"] = tool_call_id
            name = str(item.get("name") or "").strip()
            if name:
                message_payload["name"] = name
        messages.append(message_payload)
        return

    if item_type == "function_call":
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [_response_function_call_to_tool_call(item)],
            }
        )
        return

    if item_type in {"function_call_output", "tool_result"}:
        output_source = item.get("output")
        if output_source is None and "content" in item:
            output_source = item.get("content")
        output = _normalize_response_tool_output_content(output_source)
        tool_call_id = str(
            item.get("call_id") or item.get("tool_call_id") or item.get("id") or ""
        ).strip()
        if _responses_tool_output_can_follow_openai(messages, tool_call_id):
            tool_message: Dict[str, Any] = {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": output,
            }
            name = str(item.get("name") or "").strip()
            if name:
                tool_message["name"] = name
            messages.append(tool_message)
        else:
            messages.append(
                {
                    "role": "user",
                    "content": _responses_tool_output_fallback_content(item, output),
                }
            )
        return

    content = item.get("content")
    if content is None and "text" in item:
        content = item.get("text")
    normalized_content = _normalize_response_message_content(content)
    if normalized_content not in ("", [], None):
        messages.append({"role": "user", "content": normalized_content})


def _responses_input_to_messages(body: ResponsesRequest) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    instructions = str(body.instructions or "").strip()
    if instructions:
        messages.append({"role": "system", "content": instructions})
    messages.extend(_load_responses_state(body.previous_response_id))

    source = body.input
    if source in (None, "") and body.prompt not in (None, ""):
        source = body.prompt

    if isinstance(source, list):
        pending_tool_calls: List[Dict[str, Any]] = []

        def _flush_pending_tool_calls() -> None:
            nonlocal pending_tool_calls
            if not pending_tool_calls:
                return
            messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": pending_tool_calls,
                }
            )
            pending_tool_calls = []

        for item in source:
            if isinstance(item, dict) and str(item.get("type") or "").strip().lower() == "function_call":
                pending_tool_calls.append(_response_function_call_to_tool_call(item))
                continue
            _flush_pending_tool_calls()
            _append_response_input_item(messages, item)
        _flush_pending_tool_calls()
    else:
        _append_response_input_item(messages, source)

    if not messages:
        messages.append({"role": "user", "content": ""})
    return messages


def _responses_request_to_chat_request(body: ResponsesRequest, *, stream: bool) -> ChatRequest:
    return ChatRequest(
        model=body.model,
        messages=_responses_input_to_messages(body),
        stream=stream,
        temperature=body.temperature,
        max_tokens=body.max_output_tokens,
        response_format=_normalize_responses_text_format(body.text),
        tools=_normalize_responses_tools(body.tools),
        tool_choice=_normalize_response_tool_choice(body.tool_choice),
        parallel_tool_calls=body.parallel_tool_calls,
        stop=body.stop,
    )


def _response_content_part_from_media_item(item: Any, index: int) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    media_type = str(item.get("media_type") or item.get("type") or "image").strip().lower()
    ref = str(item.get("url") or item.get("data_uri") or "").strip()
    if not ref:
        return None
    if media_type == "audio":
        payload: Dict[str, Any] = {"type": "output_audio", "audio_url": ref}
    elif media_type == "video":
        payload = {"type": "output_video", "video_url": ref}
    else:
        payload = {"type": "output_image", "image_url": ref}
    payload["annotations"] = []
    payload["index"] = index
    mime = str(item.get("mime") or "").strip()
    if mime:
        payload["mime_type"] = mime
    label = str(item.get("label") or "").strip()
    if label:
        payload["label"] = label
    return payload


def _response_message_item_from_content(
    text: str,
    media_items: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    content: List[Dict[str, Any]] = []
    if text:
        content.append({"type": "output_text", "text": str(text or ""), "annotations": []})
    for item in media_items or []:
        media_part = _response_content_part_from_media_item(item, len(content))
        if media_part is not None:
            content.append(media_part)
    if not content:
        content.append({"type": "output_text", "text": "", "annotations": []})
    return {
        "id": _new_response_item_id("msg"),
        "type": "message",
        "status": "completed",
        "role": "assistant",
        "content": content,
    }


def _response_function_call_item_from_tool_call(tool_call: Dict[str, Any]) -> Dict[str, Any]:
    function_data = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
    call_id = str(tool_call.get("id") or _new_response_item_id("call")).strip()
    item_id = f"fc_{call_id[5:]}" if call_id.startswith("call_") else _new_response_item_id("fc")
    arguments = function_data.get("arguments")
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments if arguments is not None else {}, ensure_ascii=False)
    return {
        "id": item_id,
        "type": "function_call",
        "status": "completed",
        "call_id": call_id,
        "name": str(function_data.get("name") or "").strip(),
        "arguments": arguments,
    }


def _chat_payload_to_responses_output(chat_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    choices = chat_payload.get("choices") if isinstance(chat_payload.get("choices"), list) else []
    if not choices:
        return []
    message = choices[0].get("message") if isinstance(choices[0], dict) else {}
    if not isinstance(message, dict):
        return []

    output: List[Dict[str, Any]] = []
    tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
    for tool_call in tool_calls:
        if isinstance(tool_call, dict):
            output.append(_response_function_call_item_from_tool_call(tool_call))

    content = message.get("content")
    media_items = message.get("media")
    if not isinstance(media_items, list):
        media_items = chat_payload.get("media") if isinstance(chat_payload.get("media"), list) else []
    if content not in ("", None) or media_items:
        output.append(_response_message_item_from_content(str(content or ""), media_items))
    return output


def _build_responses_usage(chat_payload: Dict[str, Any]) -> Dict[str, int]:
    usage = chat_payload.get("usage") if isinstance(chat_payload.get("usage"), dict) else {}
    return {
        "input_tokens": int(usage.get("prompt_tokens") or 0),
        "output_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }


def _build_responses_text_payload(body: ResponsesRequest) -> Dict[str, Any]:
    format_payload = _normalize_responses_text_format(body.text)
    text_payload: Dict[str, Any] = {
        "format": format_payload if isinstance(format_payload, dict) else {"type": "text"},
        "verbosity": "medium",
    }
    if isinstance(body.text, dict) and body.text.get("verbosity") is not None:
        text_payload["verbosity"] = body.text.get("verbosity")
    return text_payload


def _responses_request_settings(body: ResponsesRequest) -> Dict[str, Any]:
    return {
        "max_output_tokens": body.max_output_tokens,
        "parallel_tool_calls": True if body.parallel_tool_calls is None else bool(body.parallel_tool_calls),
        "previous_response_id": body.previous_response_id,
        "reasoning": body.reasoning if isinstance(body.reasoning, dict) else {"effort": None, "summary": None},
        "store": True if body.store is None else bool(body.store),
        "temperature": body.temperature if body.temperature is not None else 1.0,
        "tool_choice": "auto" if body.tool_choice is None else body.tool_choice,
        "top_p": body.top_p if body.top_p is not None else 1.0,
        "truncation": body.truncation if body.truncation is not None else "disabled",
        "user": body.user,
        "metadata": body.metadata if isinstance(body.metadata, dict) else {},
    }


def _build_responses_object(
    body: ResponsesRequest,
    chat_payload: Dict[str, Any],
    *,
    response_id: Optional[str] = None,
    created_at: Optional[int] = None,
    status: str = "completed",
    error: Optional[Dict[str, Any]] = None,
    incomplete_details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    response_obj: Dict[str, Any] = {
        "id": response_id or _new_response_id(),
        "object": "response",
        "created_at": int(created_at if created_at is not None else time.time()),
        "status": status,
        "error": error,
        "incomplete_details": incomplete_details,
        "instructions": body.instructions,
        "model": body.model,
        "output": _chat_payload_to_responses_output(chat_payload),
        "tools": body.tools or [],
        "text": _build_responses_text_payload(body),
        "usage": _build_responses_usage(chat_payload),
    }
    response_obj.update(_responses_request_settings(body))
    if status == "completed":
        response_obj["completed_at"] = int(time.time())
    return response_obj


def _responses_completion_status_from_chat_payload(
    chat_payload: Dict[str, Any],
) -> tuple[str, Optional[Dict[str, Any]], str]:
    choices = chat_payload.get("choices") if isinstance(chat_payload.get("choices"), list) else []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        finish_reason = str(choice.get("finish_reason") or "").strip().lower()
        if finish_reason == "length":
            return "incomplete", {"reason": "max_output_tokens"}, "response.incomplete"
        if finish_reason == "content_filter":
            return "incomplete", {"reason": "content_filter"}, "response.incomplete"
    return "completed", None, "response.completed"


def _responses_error_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        result = dict(error)
        result["message"] = str(result.get("message") or "responses_backing_request_failed")
        result["type"] = str(result.get("type") or "execution_error")
        if result.get("code") is None:
            result["code"] = "responses_backing_request_failed"
        return result
    if isinstance(error, str) and error.strip():
        return {
            "message": error.strip(),
            "type": "execution_error",
            "code": "responses_backing_request_failed",
        }
    return {
        "message": "responses_backing_request_failed",
        "type": "execution_error",
        "code": "responses_backing_request_failed",
    }


def _decode_json_response(response: JSONResponse) -> Dict[str, Any]:
    raw = response.body
    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw or "")
    data = json.loads(text or "{}")
    return data if isinstance(data, dict) else {}


async def _run_chat_completion_final(
    request: Request,
    body: ChatRequest,
    authenticated: bool,
) -> tuple[int, Dict[str, Any]]:
    """Invoke the validated browser worker through the only remaining chat seam."""

    from app.api.chat import chat_completions

    if body.stream is False:
        effective_body = body
    elif hasattr(body, "model_copy"):
        effective_body = body.model_copy(update={"stream": False})
    else:
        effective_body = body.copy(update={"stream": False})

    response = await chat_completions(
        request=request,
        body=effective_body,
        authenticated=authenticated,
    )
    if not isinstance(response, JSONResponse):
        raise RuntimeError("responses_backing_request_unexpected_response_type")
    return int(response.status_code), _decode_json_response(response)


__all__ = [
    "ChatRequest",
    "ResponsesRequest",
    "_build_responses_object",
    "_load_responses_state",
    "_new_response_id",
    "_responses_completion_status_from_chat_payload",
    "_responses_error_payload",
    "_responses_request_to_chat_request",
    "_run_chat_completion_final",
    "_store_responses_state",
    "verify_auth",
]
