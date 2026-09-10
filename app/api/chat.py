"""Compatibility facade for the standalone Codex Web Bridge.

The standalone tree keeps this historically imported module as a narrow facade
for Codex protocol helpers. Browser execution and Responses fallback now route
through extracted standalone modules; the integrated generic chat runtime is no
longer part of this facade's dependency graph.
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

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
from app.services.codex_chatgpt_executor import execute_chatgpt_nonstream


async def chat_completions(*args: Any, **kwargs: Any):
    """Run the compatibility chat call through the standalone ChatGPT executor."""

    status_code, payload = await execute_chatgpt_nonstream(*args, **kwargs)
    return JSONResponse(content=payload, status_code=status_code)


async def create_response(*args: Any, **kwargs: Any):
    """Serve the remaining Responses compatibility path without generic UWA routing."""

    from app.api.standalone_responses_backing import create_response as implementation

    return await implementation(*args, **kwargs)


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
