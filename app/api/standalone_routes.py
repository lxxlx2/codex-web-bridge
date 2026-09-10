"""Standalone Codex-only API route aggregate.

This module intentionally registers only the routes needed by Codex Web Bridge.
It keeps the verified runtime patch installation order from the integrated UWA
baseline while avoiding eager registration of unrelated generic-provider APIs,
dashboard/config routes, browser administration routes and command endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.codex_compat import router as codex_compat_router
from app.api.codex_compact import router as codex_compact_router
from app.api.codex_responses_v2 import router as codex_responses_v2_router
from app.services.codex_required_tool_language_patch import (
    install_codex_required_tool_language_patch,
)
from app.services.codex_workspace_refusal_language_patch import (
    install_codex_workspace_refusal_language_patch,
)
from app.services.codex_remote_compaction_v2 import install_codex_remote_compaction_v2
from app.services.codex_v2_runtime_hardening import install_codex_v2_runtime_hardening
from app.services.codex_stream_compat import install_codex_stream_compat


install_codex_required_tool_language_patch()
install_codex_workspace_refusal_language_patch()
install_codex_remote_compaction_v2()
install_codex_v2_runtime_hardening()
install_codex_stream_compat()

router = APIRouter()
router.include_router(codex_compat_router)
router.include_router(codex_compact_router)
router.include_router(codex_responses_v2_router)

__all__ = ["router"]
