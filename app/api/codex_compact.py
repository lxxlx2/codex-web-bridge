"""Codex-compatible unary /v1/responses/compact endpoint.

Codex legacy remote compaction sends canonical Responses history to this endpoint
and installs the returned ``output`` items as replacement history. UWA uses the
already configured ChatGPT Web model to produce a compact assistant summary.

This route intentionally does not expose client tools during compaction and does
not fabricate OpenAI encrypted compaction blobs. The returned assistant message
is a valid replacement-history item for the legacy Responses compact path.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.chat import (
    ResponsesRequest,
    _build_responses_object,
    _responses_request_to_chat_request,
    _run_chat_completion_final,
    verify_auth,
)
from app.api.codex_responses import (
    _require_loopback,
    _sanitize_codex_root_workdirs,
    _sanitize_codex_tool_payload,
)
from app.core.config import get_logger
from app.services.chatgpt_web_mode import web_mode_enabled
from app.services.codex_network_tuning import install_codex_chatgpt_network_tuning
from app.services.codex_web_policy import prepare_and_verify_codex_web_mode


router = APIRouter()
logger = get_logger("API.CODEX_COMPACT")

_COMPACT_INSTRUCTIONS = """[Codex Context Compaction]
Create a compact replacement-history summary for a long-running coding thread.
Preserve facts needed to continue work correctly: user goals, explicit constraints,
important decisions, repository/file paths, edits already made, tests and their
results, failures and diagnoses, unresolved work, and the next intended actions.
Do not invent facts. Do not call tools. Do not output function calls. Do not add
ceremonial prose. Return only the concise continuation summary for the next model
turn. Prefer durable facts over transient chatter or verbose command output.
"""


class CodexCompactRequest(BaseModel):
    model: str = Field(default="unknown")
    input: List[Any] = Field(default_factory=list)
    instructions: str = Field(default="")
    tools: Optional[Any] = Field(default=None)
    parallel_tool_calls: bool = Field(default=True)
    reasoning: Optional[dict] = Field(default=None)
    service_tier: Optional[str] = Field(default=None)
    prompt_cache_key: Optional[str] = Field(default=None)
    text: Optional[dict] = Field(default=None)


def compact_request_to_responses(body: CodexCompactRequest) -> ResponsesRequest:
    original_instructions = str(body.instructions or "").strip()
    instructions = _COMPACT_INSTRUCTIONS
    if original_instructions:
        instructions += (
            "\nActive thread instructions follow for context. Preserve only constraints "
            "that are necessary for correct continuation; do not quote them wholesale.\n\n"
            + original_instructions
        )

    return ResponsesRequest(
        model=body.model,
        input=list(body.input or []),
        instructions=instructions,
        stream=False,
        store=False,
        tools=None,
        tool_choice="none",
        parallel_tool_calls=False,
        reasoning=body.reasoning,
        text=None,
        max_output_tokens=12000,
    )


def compact_output_items(body: ResponsesRequest, chat_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    response = _build_responses_object(body, chat_payload)
    output = response.get("output") if isinstance(response, dict) else None
    if not isinstance(output, list):
        return []

    compacted: List[Dict[str, Any]] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        role = str(item.get("role") or "").strip().lower()
        if item_type == "message" and role == "assistant":
            compacted.append(item)
    return compacted


@router.post("/v1/responses/compact")
async def codex_responses_compact(
    request: Request,
    body: CodexCompactRequest,
    authenticated: bool = Depends(verify_auth),
):
    _require_loopback(request)

    if not web_mode_enabled():
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "message": "Codex ChatGPT Web mode is disabled",
                    "type": "service_unavailable",
                    "code": "codex_web_mode_disabled",
                }
            },
        )

    responses_body = compact_request_to_responses(body)

    try:
        prepare_and_verify_codex_web_mode(responses_body.reasoning)
        install_codex_chatgpt_network_tuning()
        chat_body = _responses_request_to_chat_request(responses_body, stream=False)
        status_code, raw_payload = await _run_chat_completion_final(
            request=request,
            body=chat_body,
            authenticated=authenticated,
        )
    except Exception as exc:
        logger.warning(f"Codex compact backing request failed: {exc}")
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "message": "Codex compact backing request failed",
                    "type": "execution_error",
                    "code": "responses_compact_backing_failed",
                }
            },
        )

    payload = _sanitize_codex_root_workdirs(
        _sanitize_codex_tool_payload(raw_payload),
        chat_body.messages,
    )
    if status_code >= 400 or not isinstance(payload, dict) or "error" in payload:
        return JSONResponse(
            status_code=max(400, int(status_code or 502)),
            content={
                "error": {
                    "message": "Codex compact backing request returned an error",
                    "type": "execution_error",
                    "code": "responses_compact_backing_error",
                }
            },
        )

    output = compact_output_items(responses_body, payload)
    if not output:
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "message": "Codex compact backing request produced no assistant summary",
                    "type": "invalid_response_error",
                    "code": "responses_compact_missing_summary",
                }
            },
        )

    logger.info(f"[CODEX_COMPACT] compacted history into {len(output)} assistant item(s)")
    return {"output": output}
