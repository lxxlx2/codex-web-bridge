"""Compatibility facade for the standalone Codex Web Bridge.

The original Universal Web API chat module carried the validated ChatGPT Web
browser worker together with a large amount of generic provider/API code.  S2
keeps that implementation in :mod:`app.api.legacy_chat_runtime` while making
this historically imported module cheap to import.

Codex protocol types and conversion/state helpers come from the standalone
runtime.  The browser worker and any legacy-only attribute are loaded only when
actually used.  This preserves compatibility during extraction without pulling
the full generic chat graph into ``import main``.
"""

from __future__ import annotations

from typing import Any

from app.api.codex_runtime import (
    ChatRequest,
    ResponsesRequest,
    _build_responses_object,
    _load_responses_state,
    _new_response_id,
    _responses_completion_status_from_chat_payload,
    _responses_error_payload,
    _responses_request_to_chat_request,
    _run_chat_completion_final,
    _store_responses_state,
    verify_auth,
)


async def chat_completions(*args: Any, **kwargs: Any):
    """Lazily enter the validated legacy browser execution worker."""

    from app.api.legacy_chat_runtime import chat_completions as implementation

    return await implementation(*args, **kwargs)


async def create_response(*args: Any, **kwargs: Any):
    """Compatibility fallback while the remaining generic Responses path is retired."""

    from app.api.legacy_chat_runtime import create_response as implementation

    return await implementation(*args, **kwargs)


def __getattr__(name: str) -> Any:
    """Resolve legacy-only symbols without making them import-time dependencies."""

    from app.api import legacy_chat_runtime

    try:
        value = getattr(legacy_chat_runtime, name)
    except AttributeError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    globals()[name] = value
    return value


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
    "chat_completions",
    "create_response",
    "verify_auth",
]
