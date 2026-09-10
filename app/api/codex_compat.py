"""Codex-specific compatibility helpers.

Codex 0.153+ requests ``<provider base_url>/models?client_version=...`` and
expects its own model-catalog schema (``{"models": [...]}``) rather than the
standard OpenAI ``{"object": "list", "data": [...]}`` shape.

Keep the public OpenAI-compatible models response unchanged for every other
client. Codex is detected by the query parameter it unconditionally appends
to model-catalog requests.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, Query

from app.api.chat import list_models as list_openai_models


router = APIRouter()


# The ChatGPT Web preflight now maps Codex medium/high to the corresponding
# browser reasoning controls.  Low/ultra remain hidden until they are verified
# end-to-end on the web UI.
_REASONING_LEVELS = [
    {
        "effort": "medium",
        "description": "GPT-5.6 Sol · Medium",
    },
    {
        "effort": "high",
        "description": "GPT-5.6 Sol · High",
    },
]

# Keep the browser-bridge system prompt compact. Codex still sends tool schemas
# and workspace context separately, so a concise instruction template avoids
# wasting a large portion of each webpage request on generic agent boilerplate.
_CODEX_INSTRUCTIONS = """You are the reasoning model for a coding client working in the user's local workspace.
The browser page itself has no direct filesystem access. Declared client tools such as exec_command run on the user's machine under the client's sandbox and approval policy.
For local workspace tasks, inspect the real workspace with the declared client tools. Do not ask the user to upload local files or run commands manually when an appropriate client tool is available.
Use tool results as the source of truth. Never claim a file, command, edit, or test was completed unless a tool result confirms it.
Make only changes needed for the user's request, run the most relevant checks after code changes, keep progress concise, and finish with the verified result plus any unresolved issue that matters.
""".strip()


def _canonical_model_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Hide obvious hostname aliases while preserving real model identifiers."""
    by_owner: Dict[str, List[Dict[str, Any]]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        owner = str(entry.get("owned_by") or "universal-web-api").strip().lower()
        by_owner.setdefault(owner, []).append(entry)

    result: List[Dict[str, Any]] = []
    for owner_entries in by_owner.values():
        owner = str(owner_entries[0].get("owned_by") or "").strip().lower()
        host_aliases = {owner, f"www.{owner}"} if owner else set()
        non_host_entries = [
            entry
            for entry in owner_entries
            if str(entry.get("id") or "").strip().lower() not in host_aliases
        ]
        result.extend(non_host_entries or owner_entries[:1])
    return result


def _to_codex_model(entry: Dict[str, Any], priority: int) -> Dict[str, Any]:
    model_id = str(entry.get("id") or "chatgpt").strip() or "chatgpt"
    raw_display_name = str(entry.get("display_name") or model_id).strip() or model_id
    owner = str(entry.get("owned_by") or "universal-web-api").strip()

    if model_id.lower() == "chatgpt" and owner.lower() in {"chatgpt.com", "www.chatgpt.com"}:
        display_name = "GPT-5.6 Sol"
        description = (
            "UWA controlled ChatGPT Web route. Before each Codex Responses request, "
            "the bridge applies and verifies GPT-5.6 Sol plus the selected Medium/High "
            "reasoning level; strict mode fails instead of silently using an unknown mode."
        )
    else:
        display_name = raw_display_name
        description = f"Universal Web API browser route ({owner})"

    # Conservative local-browser limits. Increase only after empirical stability
    # tests for the specific web model/browser workflow.
    context_window = 64_000

    return {
        "slug": model_id,
        "display_name": display_name,
        "description": description,
        "default_reasoning_level": "high",
        "supported_reasoning_levels": _REASONING_LEVELS,
        # ``shell_command`` is an accepted alias for Codex UnifiedExec. Local
        # execution still happens inside Codex, never inside this web bridge.
        "shell_type": "shell_command",
        "visibility": "list",
        "supported_in_api": True,
        "priority": priority,
        "availability_nux": None,
        "upgrade": None,
        "model_messages": {"instructions_template": _CODEX_INSTRUCTIONS},
        "include_skills_usage_instructions": False,
        "include_plugin_usage_instructions": False,
        "include_apps_usage_instructions": False,
        "support_verbosity": False,
        "default_verbosity": None,
        "apply_patch_tool_type": None,
        "truncation_policy": {"mode": "tokens", "limit": 57_600},
        "supports_image_detail_original": False,
        "context_window": context_window,
        "max_context_window": context_window,
        "minimal_client_version": [0, 1, 0],
        "experimental_supported_tools": [],
    }


def build_codex_models_response(openai_payload: Any) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    if isinstance(openai_payload, dict):
        raw_entries = openai_payload.get("data")
        if isinstance(raw_entries, list):
            entries = [entry for entry in raw_entries if isinstance(entry, dict)]

    canonical_entries = _canonical_model_entries(entries)
    models = [
        _to_codex_model(entry, priority=index + 1)
        for index, entry in enumerate(canonical_entries)
    ]
    return {"models": models}


@router.get("/v1/models")
async def codex_aware_models(
    client_version: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
    anthropic_version: Optional[str] = Header(None, alias="anthropic-version"),
):
    # Delegate first so existing authentication and dynamic model collection
    # remain the single source of truth.
    payload = await list_openai_models(
        authorization=authorization,
        x_api_key=x_api_key,
        anthropic_version=anthropic_version,
    )

    if not str(client_version or "").strip():
        return payload

    return build_codex_models_response(payload)
