"""Compatibility detector extensions for explicit Codex client-tool requests.

Live macOS acceptance exposed wording gaps in the V2 required-tool contract.
The acceptance harness may say forms such as ``必须通过客户端 exec_command`` or
``必须单独调用一次客户端 exec_command`` while the original detector covered
direct forms such as ``必须使用 exec_command``. H3 later exposed the same gap for
imperative English wording such as ``First use exec_command to run:``. A web
model could therefore complete without a real client function call and escape
strict repair.

This module extends only the request-language detector. It does not execute
commands or change Codex sandbox/approval behavior.
"""

from __future__ import annotations

import re
from typing import Any


_CLIENT_PREFIXED_REQUIRED_TOOL_PATTERN = re.compile(
    r"(?:必须|务必|一定要|请务必|只能)\s*"
    r"(?:先|再)?\s*"
    r"(?:单独\s*)?"
    r"(?:通过|使用|调用|执行)?\s*"
    r"(?:一次|一遍|一个)?\s*"
    r"(?:客户端\s*)?`?"
    r"(exec_command|shell_command|local_shell|apply_patch|write_stdin)`?",
    re.IGNORECASE,
)

_CLIENT_IMPERATIVE_REQUIRED_TOOL_PATTERN = re.compile(
    r"^\s*(?:first\s+)?(?:please\s+)?(?:use|call|invoke)\s+"
    r"(?:the\s+(?:local\s+)?client\s+)?`?"
    r"(exec_command|shell_command|local_shell|apply_patch|write_stdin)`?"
    r"(?:\s+tool)?\b",
    re.IGNORECASE | re.MULTILINE,
)

_INSTALLED = False


def install_codex_required_tool_language_patch() -> None:
    """Extend V2 detection for explicit Chinese and English tool imperatives."""

    global _INSTALLED
    if _INSTALLED:
        return

    from app.api import codex_responses_v2 as v2

    existing = tuple(getattr(v2, "_REQUIRED_TOOL_PATTERNS", ()) or ())
    existing_text = {str(getattr(item, "pattern", "")) for item in existing}
    extensions = (
        _CLIENT_PREFIXED_REQUIRED_TOOL_PATTERN,
        _CLIENT_IMPERATIVE_REQUIRED_TOOL_PATTERN,
    )
    additions = tuple(
        pattern
        for pattern in extensions
        if str(getattr(pattern, "pattern", "")) not in existing_text
    )
    if additions:
        v2._REQUIRED_TOOL_PATTERNS = (*additions, *existing)

    _INSTALLED = True


def client_prefixed_required_tool_pattern() -> Any:
    """Expose the compiled Chinese pattern for focused regression tests."""

    return _CLIENT_PREFIXED_REQUIRED_TOOL_PATTERN


def client_imperative_required_tool_pattern() -> Any:
    """Expose the compiled English imperative pattern for focused tests."""

    return _CLIENT_IMPERATIVE_REQUIRED_TOOL_PATTERN


__all__ = [
    "client_imperative_required_tool_pattern",
    "client_prefixed_required_tool_pattern",
    "install_codex_required_tool_language_patch",
]
