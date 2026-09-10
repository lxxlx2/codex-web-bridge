"""Narrow runtime compatibility patch for Codex workspace-refusal wording.

Live Stage E acceptance exposed a ChatGPT Web answer that claimed the current
execution environment did not contain the active Codex workspace path even though
Codex had resumed the same thread and had declared local workspace tools.

The generic client-tool policy already repairs local workspace refusals. This
module only extends its refusal-language matcher for the observed path-oriented
Chinese wording. It does not execute tools and does not change sandbox/approval
semantics.
"""

from __future__ import annotations

import re

from app.core.config import get_logger


logger = get_logger("CODEX_WORKSPACE_REFUSAL")
_INSTALLED = False

_PATH_REFUSAL_PATTERNS = (
    re.compile(
        r"(?:当前|这轮|现在)?.{0,50}(?:可用|可访问|实际)?(?:执行环境|会话环境|文件系统|工作区)"
        r".{0,100}(?:不存在|找不到|不可访问|无法访问|没有|未挂载|未映射)"
        r".{0,140}(?:/Users/|/home/|[A-Za-z]:\\)",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"(?:/Users/|/home/|[A-Za-z]:\\)[^\s`'\"]*"
        r".{0,100}(?:不存在|找不到|不可访问|无法访问|未挂载|未映射)",
        re.IGNORECASE | re.DOTALL,
    ),
)


def looks_like_codex_workspace_path_refusal(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return any(pattern.search(value) for pattern in _PATH_REFUSAL_PATTERNS)


def install_codex_workspace_refusal_language_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from app.services import client_tool_policy as policy

    current = policy.looks_like_client_access_refusal
    if bool(getattr(current, "_uwa_codex_workspace_path_refusal_guarded", False)):
        _INSTALLED = True
        return

    def _wrapped(text: str) -> bool:
        if current(text):
            return True
        return looks_like_codex_workspace_path_refusal(text)

    setattr(_wrapped, "_uwa_codex_workspace_path_refusal_guarded", True)
    policy.looks_like_client_access_refusal = _wrapped
    _INSTALLED = True
    logger.info("[CODEX_WORKSPACE_REFUSAL] path-oriented refusal compatibility installed")


__all__ = [
    "install_codex_workspace_refusal_language_patch",
    "looks_like_codex_workspace_path_refusal",
]
