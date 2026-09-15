"""Classification and deterministic local handling for Codex UI metadata helpers.

Codex Desktop/TUI can create hidden structured requests to generate thread titles
or nearby search metadata. Those requests may embed the real user prompt as data.
They must never be treated as agent turns, required-client-tool requests, or web
session affinity owners.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict


_REQUEST_SEPARATOR = "User prompt:"
_CURRENT_TITLE_MARKERS = (
    "Generate a concise, single-line task title",
    "Do not answer the request.",
    _REQUEST_SEPARATOR,
)
_LEGACY_UI_MARKERS = (
    "Generate a concise",
    "title",
    "description",
    _REQUEST_SEPARATOR,
)


def _schema(text_config: Any) -> Dict[str, Any]:
    if not isinstance(text_config, dict):
        return {}
    fmt = text_config.get("format")
    if not isinstance(fmt, dict):
        return {}
    if str(fmt.get("type") or "").strip().lower() != "json_schema":
        return {}
    payload = fmt.get("json_schema") if isinstance(fmt.get("json_schema"), dict) else fmt
    schema = payload.get("schema") if isinstance(payload, dict) else None
    return schema if isinstance(schema, dict) else {}


def _schema_properties(text_config: Any) -> Dict[str, Any]:
    schema = _schema(text_config)
    properties = schema.get("properties")
    return properties if isinstance(properties, dict) else {}


def classify_metadata_helper(prompt: str, text_config: Any) -> str:
    """Return a narrow helper kind or an empty string for a real agent turn."""

    prompt = str(prompt or "")
    properties = _schema_properties(text_config)
    if "title" not in properties:
        return ""

    current_title = all(marker in prompt for marker in _CURRENT_TITLE_MARKERS)
    if current_title:
        return "metadata_helper"

    lower = prompt.lower()
    legacy = all(marker.lower() in lower for marker in _LEGACY_UI_MARKERS)
    explicit_non_answer = (
        "do not answer" in lower
        or "don't answer" in lower
        or "metadata" in lower
    )
    has_description_shape = any(
        key in properties
        for key in ("description", "search_description", "preview")
    )
    if legacy and explicit_non_answer and has_description_shape:
        return "metadata_helper"

    return ""


def extract_embedded_user_prompt(prompt: str) -> str:
    text = str(prompt or "")
    if _REQUEST_SEPARATOR not in text:
        return ""
    return text.split(_REQUEST_SEPARATOR, 1)[1].strip()


def _limit_for_property(spec: Any, default: int) -> int:
    if not isinstance(spec, dict):
        return default
    raw = spec.get("maxLength")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, 512))


def _normalize_one_line(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    text = text.strip("`\"' ")
    return text.rstrip(".!?。！？,，;；:： ")


def _truncate_chars(text: str, limit: int) -> str:
    value = str(text or "")
    return value if len(value) <= limit else value[:limit].rstrip()


def _title_from_user_prompt(user_prompt: str, limit: int) -> str:
    source = _normalize_one_line(user_prompt)
    if not source:
        return _truncate_chars("Handle request", limit)
    contains_cjk = bool(re.search(r"[\u3400-\u9fff]", source))
    prefix = "处理" if contains_cjk else "Handle "
    if contains_cjk:
        candidate = prefix + source
    else:
        candidate = source if re.match(r"^[A-Za-z]+\b", source) else prefix + source
    candidate = _normalize_one_line(candidate)
    return _truncate_chars(candidate or "Handle request", limit)


def _description_from_user_prompt(user_prompt: str, limit: int) -> str:
    source = _normalize_one_line(user_prompt) or "Request"
    return _truncate_chars(source, limit)


def build_metadata_result(prompt: str, text_config: Any) -> Dict[str, Any]:
    """Build a schema-shaped, bounded result without calling ChatGPT Web."""

    properties = _schema_properties(text_config)
    required = _schema(text_config).get("required")
    required_names = [str(item) for item in required] if isinstance(required, list) else []
    user_prompt = extract_embedded_user_prompt(prompt)
    result: Dict[str, Any] = {}

    for name, spec in properties.items():
        key = str(name)
        if key == "title":
            result[key] = _title_from_user_prompt(
                user_prompt,
                _limit_for_property(spec, 36),
            )
        elif key in {"description", "search_description", "preview"}:
            result[key] = _description_from_user_prompt(
                user_prompt,
                _limit_for_property(spec, 160),
            )
        elif key in required_names and isinstance(spec, dict):
            kind = str(spec.get("type") or "").strip().lower()
            if kind == "string":
                result[key] = _truncate_chars("Request", _limit_for_property(spec, 64))
            elif kind == "boolean":
                result[key] = False
            elif kind in {"integer", "number"}:
                result[key] = 0
            elif kind == "array":
                result[key] = []
            elif kind == "object":
                result[key] = {}

    if "title" not in result:
        result["title"] = "Handle request"
    return result


def build_metadata_json(prompt: str, text_config: Any) -> str:
    return json.dumps(
        build_metadata_result(prompt, text_config),
        ensure_ascii=False,
        separators=(",", ":"),
    )


__all__ = [
    "build_metadata_json",
    "build_metadata_result",
    "classify_metadata_helper",
    "extract_embedded_user_prompt",
]
