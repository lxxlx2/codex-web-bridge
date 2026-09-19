"""Narrow runtime compatibility patch for Codex workspace-refusal wording.

Live Stage E acceptance exposed a ChatGPT Web answer that claimed the current
execution environment did not contain the active Codex workspace path even though
Codex had resumed the same thread and had declared local workspace tools.

The generic client-tool policy already repairs local workspace refusals. This
module only extends its refusal-language matcher for the observed path-oriented
Chinese wording. It also preserves a narrow piece of tool provenance when a
Responses ``function_call_output`` had to be represented as the generated
``[Function Call Output ...]`` user fallback. It does not execute tools and does
not change sandbox/approval semantics.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

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


def _latest_function_output_fallback(messages: List[Dict[str, Any]]) -> bool:
    """Recognize only the bridge-generated Responses tool-result fallback."""

    for message in reversed(messages or []):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "user").strip().lower() != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            text = content
        else:
            try:
                import json

                text = json.dumps(content, ensure_ascii=False)
            except Exception:
                text = str(content or "")
        return text.lstrip().startswith("[Function Call Output")
    return False


def install_codex_workspace_refusal_language_patch() -> None:
    global _INSTALLED

    from app.services import client_tool_policy as policy

    access_marker = "_uwa_codex_workspace_path_refusal_guarded"
    post_tool_marker = "_uwa_codex_workspace_path_refusal_post_tool_guarded"
    decision_marker = "_uwa_codex_workspace_function_output_refusal_guarded"

    current_access = policy.looks_like_client_access_refusal
    current_post_tool = policy.looks_like_post_tool_unavailable_claim
    current_decision = policy.should_repair_client_workspace_refusal

    access_guarded = bool(getattr(current_access, access_marker, False))
    post_tool_guarded = bool(getattr(current_post_tool, post_tool_marker, False))
    decision_guarded = bool(getattr(current_decision, decision_marker, False))

    if access_guarded and post_tool_guarded and decision_guarded:
        _INSTALLED = True
        return

    if not access_guarded:
        def _wrapped_access(text: str) -> bool:
            if current_access(text):
                return True
            return looks_like_codex_workspace_path_refusal(text)

        setattr(_wrapped_access, access_marker, True)
        policy.looks_like_client_access_refusal = _wrapped_access

    if not post_tool_guarded:
        def _wrapped_post_tool(text: str) -> bool:
            if current_post_tool(text):
                return True
            return looks_like_codex_workspace_path_refusal(text)

        setattr(_wrapped_post_tool, post_tool_marker, True)
        policy.looks_like_post_tool_unavailable_claim = _wrapped_post_tool

    if not decision_guarded:
        def _wrapped_decision(
            *,
            messages: List[Dict[str, Any]],
            tools: List[Dict[str, Any]],
            tool_choice: Any,
            assistant_text: str,
            parsed: Dict[str, Any],
        ) -> bool:
            if current_decision(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                assistant_text=assistant_text,
                parsed=parsed,
            ):
                return True

            # A Responses function_call_output can arrive on an affinity delta
            # without its matching assistant call being representable in the
            # local Chat-shaped message list. The generated fallback is still
            # authoritative proof that a real client tool result exists. If the
            # model then claims that the same local workspace/path is missing,
            # force the existing bounded repair loop instead of accepting that
            # contradiction as a final answer.
            if isinstance(tool_choice, str) and tool_choice.strip().lower() == "none":
                return False
            if not policy.has_client_workspace_tools(tools):
                return False
            if parsed.get("tool_calls"):
                return False
            if str(parsed.get("mode") or "").strip().lower() != "final":
                return False
            if not _latest_function_output_fallback(messages):
                return False
            return looks_like_codex_workspace_path_refusal(assistant_text)

        setattr(_wrapped_decision, decision_marker, True)
        policy.should_repair_client_workspace_refusal = _wrapped_decision

        # tool_calling imports the decision function by value, so update that
        # module-local reference when it is already loaded.
        try:
            from app.services import tool_calling

            tool_calling.should_repair_client_workspace_refusal = _wrapped_decision
        except Exception:
            pass

    _INSTALLED = True

    logger.info(
        "[CODEX_WORKSPACE_REFUSAL] "
        "path-oriented refusal compatibility installed"
    )


__all__ = [
    "install_codex_workspace_refusal_language_patch",
    "looks_like_codex_workspace_path_refusal",
]
