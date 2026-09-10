"""Client-side coding tool policy for web-model tool calling.

Web chat models often assume that they cannot access a user's local machine. In a
Codex-style client this assumption is incomplete: the web page itself has no local
filesystem access, but declared function tools such as ``exec_command`` execute in
the client under the client's own sandbox and approval policy.

This module repairs a narrow class of contradictions where the web model claims
that the local workspace or client execution tool is unavailable even though the
client declared that tool. It also rejects an accidental root ``workdir`` override
for client shell tools unless the user explicitly asked to execute from filesystem
root. It never executes commands itself and it never bypasses client permission
checks.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List


_WORKSPACE_TOOL_PRIORITY = (
    "exec_command",
    "shell_command",
    "local_shell",
    "apply_patch",
    "write_stdin",
)

_EXEC_LIKE_TOOLS = {"exec_command", "shell_command", "local_shell"}

_WORKSPACE_REQUEST_PATTERNS = (
    re.compile(r"\bworkspace\b", re.IGNORECASE),
    re.compile(r"\brepo(?:sitory)?\b", re.IGNORECASE),
    re.compile(r"\blocal\s+(?:file|directory|project|workspace)\b", re.IGNORECASE),
    re.compile(r"\b(?:read|inspect|open|edit|modify|fix|patch|test|run)\b.{0,80}\b(?:file|code|test|project|repo)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:^|[\s/])[^\s/]+\.(?:py|js|jsx|ts|tsx|java|kt|kts|cs|cpp|cc|c|h|hpp|go|rs|rb|php|swift|sh|zsh|bash|toml|yaml|yml|json|md)(?:\b|$)", re.IGNORECASE),
    re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\)", re.IGNORECASE),
    re.compile(r"\b(?:exec_command|shell_command|local_shell|apply_patch|write_stdin)\b", re.IGNORECASE),
    re.compile(r"(?:本机|本地|工作区|仓库|项目|文件|目录|代码|测试|修复|修改|检查)"),
)

_REFUSAL_PATTERNS = (
    re.compile(r"\b(?:i\s+)?(?:can(?:not|'t)|do\s+not|don't)\s+(?:directly\s+)?(?:access|see|read|modify|edit)\b.{0,100}\b(?:local|machine|computer|filesystem|file|workspace|directory)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bno\s+access\s+to\b.{0,100}\b(?:local|machine|filesystem|file|workspace)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\b(?:not|isn't|is not)\s+(?:mounted|mapped)\b.{0,100}\b(?:workspace|directory|path|filesystem|file)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\b(?:workspace|directory|path|filesystem|file)\b.{0,100}\b(?:not|isn't|is not)\s+(?:mounted|mapped|available|accessible)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\b(?:please|you\s+need\s+to)\s+upload\b.{0,80}\b(?:file|project|repo)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\b(?:run|execute)\s+(?:these|the\s+following)\s+commands?\s+(?:yourself|locally|on\s+your\s+machine)\b", re.IGNORECASE),
    re.compile(r"\b(?:exec_command|shell_command|local_shell|apply_patch|write_stdin)\b.{0,80}\b(?:unavailable|not\s+available|not\s+exposed|not\s+provided|not\s+callable|missing)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:exec_command|shell_command|local_shell|apply_patch|write_stdin|客户端工具|执行工具).{0,40}(?:不可用|无法使用|不能使用|未提供|未暴露|不存在)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:不可用|无法使用|不能使用|未提供|未暴露|不存在).{0,40}(?:exec_command|shell_command|local_shell|apply_patch|write_stdin|客户端工具|执行工具)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:无法|不能|没法|访问不到).{0,30}(?:本机|本地|工作区|目录|文件)"),
    re.compile(r"(?:当前这个会话环境|当前会话环境).{0,40}(?:访问不到|无法访问|不能访问)"),
    re.compile(r"(?:当前(?:这个)?会话|当前环境|会话环境).{0,100}(?:文件系统|filesystem).{0,100}(?:没有|未|无法).{0,25}(?:挂载|映射|访问|看到|包含)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:没有|未).{0,25}(?:挂载|映射).{0,100}(?:/Users/|/home/|工作区|目录|文件|workspace)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:当前(?:可用|实际可用)?(?:执行环境|环境|会话环境)|当前(?:这个)?会话).{0,120}(?:不存在|没有|找不到|不可访问|无法访问).{0,160}(?:/Users/|/home/|[A-Za-z]:\\|工作区|路径|目录|文件)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\).{0,160}(?:不存在|不可访问|无法访问|找不到|未挂载)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:没有发现|未发现).{0,30}(?:已上传|上传的).{0,20}(?:文件|代码)"),
    re.compile(r"(?:请|需要你).{0,20}上传.{0,20}(?:文件|项目|代码)"),
    re.compile(r"你可以直接在.{0,30}(?:本地|工作区).{0,20}执行"),
    re.compile(r"(?:需要|必须).{0,50}(?:能够|可以).{0,25}访问.{0,35}(?:本机|本地|工作区).{0,35}(?:执行工具|工具)"),
    re.compile(r"(?:无法|不能).{0,30}(?:真实|真正|实际).{0,20}(?:读取|修改|测试|访问|运行)"),
    re.compile(r"(?:因此|所以).{0,35}(?:无法|不能).{0,50}(?:读取|修改|测试|运行|访问)"),
)

# Strong contradiction patterns that remain invalid even after a prior tool result.
# A previous client tool call proves the declared client-side tool existed. A later
# claim that the tool was never exposed, or that the same client execution
# environment suddenly has no mounted workspace despite a successful read, should
# be repaired rather than accepted as a final answer.
_POST_TOOL_UNAVAILABLE_PATTERNS = (
    re.compile(r"\b(?:exec_command|shell_command|local_shell|apply_patch|write_stdin)\b.{0,100}\b(?:not|isn't|is not|wasn't|was not)\s+(?:available|exposed|provided|enabled|accessible)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\b(?:no|without)\s+(?:local\s+)?(?:execution|shell|workspace)\s+tool\b", re.IGNORECASE),
    re.compile(r"\b(?:tool|client tool)\b.{0,100}\b(?:not|isn't|is not)\s+(?:available|exposed|provided|enabled)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\b(?:available|callable|declared|provided|exposed)\s+(?:client\s+)?tools?\b.{0,140}\b(?:do(?:es)?\s+not|don't|doesn't|cannot|can't|no)\b.{0,100}\b(?:include|contain|have|list|expose|provide)?\b.{0,80}\b(?:exec_command|shell_command|local_shell|apply_patch|write_stdin)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\b(?:exec_command|shell_command|local_shell|apply_patch|write_stdin)\b.{0,120}\b(?:missing|absent)\b.{0,80}\b(?:tool|tools|toolset|tool list)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:没有|未|并未|未能).{0,30}(?:暴露|提供|启用|开放).{0,40}(?:exec_command|shell_command|本地执行工具|执行工具|客户端工具)"),
    re.compile(r"(?:exec_command|shell_command|本地执行工具|执行工具|客户端工具).{0,40}(?:没有|未|并未).{0,20}(?:暴露|提供|启用|开放|可用)"),
    re.compile(r"(?:当前(?:这个)?会话|当前环境).{0,80}(?:没有|未).{0,30}(?:exec_command|本地执行工具|执行工具|客户端工具)"),
    re.compile(r"(?:当前|这轮|现在)?.{0,30}(?:实际)?(?:可调用|可用|提供|暴露)(?:的)?.{0,30}(?:客户端)?工具.{0,50}(?:没有|不存在|不包含|不含|找不到).{0,35}(?:名为\s*)?(?:exec_command|shell_command|本地执行工具|执行工具|客户端工具)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:当前|这轮|现在)?.{0,30}(?:实际)?(?:可调用|可用)(?:工具|工具列表|tool list).{0,60}(?:没有|不存在|不包含|不含).{0,35}(?:exec_command|shell_command|local_shell|apply_patch|write_stdin)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:无法|不能).{0,40}(?:真实|实际).{0,30}(?:写入|修改|运行|测试).{0,100}(?:因为|由于).{0,80}(?:工具|exec_command).{0,50}(?:没有|未|不可用|未暴露)"),
    re.compile(r"(?:当前(?:这轮|这个)?(?:实际)?可调用的执行环境|当前(?:这个)?会话(?:实际)?可用的(?:执行环境|文件系统)|当前环境).{0,120}(?:没有|未).{0,30}(?:挂载|映射).{0,100}(?:本机|本地|工作区|目录|路径|/Users/|/home/)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:没有|未).{0,30}(?:挂载|映射).{0,100}(?:本机|本地|工作区|/Users/|/home/).{0,120}(?:无法|不能).{0,50}(?:真实|实际).{0,30}(?:写入|修改|运行|测试)", re.IGNORECASE | re.DOTALL),
)

_ROOT_WORKDIR_EXPLICIT_PATTERNS = (
    re.compile(r"\bworkdir\s*(?:=|:|to)?\s*['\"]?/['\"]?\b", re.IGNORECASE),
    re.compile(r"\b(?:cwd|working\s+directory)\s*(?:=|:|to)?\s*['\"]?/['\"]?\b", re.IGNORECASE),
    re.compile(r"\b(?:filesystem\s+root|root\s+directory)\b", re.IGNORECASE),
    re.compile(r"(?:文件系统根目录|根目录).{0,20}(?:执行|运行|workdir|cwd|/)", re.IGNORECASE),
)

_ROOT_WORKDIR_TEXT_PATTERN = re.compile(
    r"[\"']?workdir[\"']?\s*:\s*[\"']/[\"']",
    re.IGNORECASE,
)


def _flag_enabled(name: str, default: bool = True) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


def _tool_name(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    function_data = item.get("function") if isinstance(item.get("function"), dict) else {}
    return str(function_data.get("name") or item.get("name") or "").strip()


def _workspace_tool_defs(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_name = {_tool_name(item): item for item in tools or [] if _tool_name(item)}
    result: List[Dict[str, Any]] = []
    for name in _WORKSPACE_TOOL_PRIORITY:
        item = by_name.get(name)
        if isinstance(item, dict):
            result.append(item)
    return result


def has_client_workspace_tools(tools: List[Dict[str, Any]]) -> bool:
    return bool(_workspace_tool_defs(tools))


def _has_tool_history(messages: List[Dict[str, Any]]) -> bool:
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        if role in {"tool", "function"}:
            return True
        if message.get("tool_calls") or message.get("function_call"):
            return True
    return False


def _has_workspace_tool_call_history(messages: List[Dict[str, Any]]) -> bool:
    workspace_names = set(_WORKSPACE_TOOL_PRIORITY)
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            for item in tool_calls:
                if _tool_name(item) in workspace_names:
                    return True
        function_call = message.get("function_call")
        if isinstance(function_call, dict) and _tool_name(function_call) in workspace_names:
            return True
        role = str(message.get("role") or "").strip().lower()
        if role in {"tool", "function"} and str(message.get("name") or "").strip() in workspace_names:
            return True
    return False


def _latest_user_text(messages: List[Dict[str, Any]]) -> str:
    for message in reversed(messages or []):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip().lower()
        if role != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        try:
            return json.dumps(content, ensure_ascii=False)
        except Exception:
            return str(content or "")
    return ""


def looks_like_local_workspace_request(messages: List[Dict[str, Any]]) -> bool:
    text = _latest_user_text(messages).strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _WORKSPACE_REQUEST_PATTERNS)


def looks_like_client_access_refusal(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return any(pattern.search(value) for pattern in _REFUSAL_PATTERNS)


def looks_like_post_tool_unavailable_claim(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return any(pattern.search(value) for pattern in _POST_TOOL_UNAVAILABLE_PATTERNS)


def _decode_tool_arguments(tool_call: Dict[str, Any]) -> Dict[str, Any]:
    function_data = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
    raw = function_data.get("arguments")
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def user_explicitly_requested_root_workdir(messages: List[Dict[str, Any]]) -> bool:
    text = _latest_user_text(messages).strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _ROOT_WORKDIR_EXPLICIT_PATTERNS)


def has_suspicious_root_workdir_tool_call(
    messages: List[Dict[str, Any]],
    parsed: Dict[str, Any],
) -> bool:
    """Return True when an exec-like tool accidentally overrides client cwd with `/`."""

    if user_explicitly_requested_root_workdir(messages):
        return False
    for tool_call in parsed.get("tool_calls") or []:
        if not isinstance(tool_call, dict):
            continue
        if _tool_name(tool_call) not in _EXEC_LIKE_TOOLS:
            continue
        args = _decode_tool_arguments(tool_call)
        if str(args.get("workdir") or "").strip() == "/":
            return True
    return False


def should_repair_client_workspace_refusal(
    *,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    tool_choice: Any,
    assistant_text: str,
    parsed: Dict[str, Any],
) -> bool:
    """Repair false local-workspace/tool-availability claims or unsafe cwd overrides."""

    if not _flag_enabled("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", True):
        return False
    if isinstance(tool_choice, str) and tool_choice.strip().lower() == "none":
        return False
    if not has_client_workspace_tools(tools):
        return False

    if parsed.get("tool_calls"):
        return has_suspicious_root_workdir_tool_call(messages, parsed)

    if str(parsed.get("mode") or "").strip().lower() != "final":
        return False

    has_history = _has_tool_history(messages)
    if has_history:
        # Once a workspace tool has really appeared in the conversation, an
        # explicit later claim that the same declared tool is absent is a direct
        # contradiction. Do not depend on the latest user-shaped message still
        # looking like the original coding request: Codex follow-up turns often
        # encode tool output as the newest user item.
        return (
            _has_workspace_tool_call_history(messages)
            and looks_like_post_tool_unavailable_claim(assistant_text)
        )

    if not looks_like_local_workspace_request(messages):
        return False
    return looks_like_client_access_refusal(assistant_text)


def build_client_workspace_repair_messages(
    *,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    assistant_text: str,
    attempt: int,
    total_attempts: int,
) -> List[Dict[str, str]]:
    """Build a small corrective prompt without exposing additional local data."""

    workspace_tools = _workspace_tool_defs(tools)
    preferred_name = _tool_name(workspace_tools[0]) if workspace_tools else "exec_command"
    declared_names = [name for name in (_tool_name(item) for item in workspace_tools) if name]
    tool_defs = json.dumps(workspace_tools, ensure_ascii=False, indent=2)
    user_request = _latest_user_text(messages).strip()
    if len(user_request) > 2200:
        user_request = user_request[:2197] + "..."
    rejected = str(assistant_text or "").strip()
    if len(rejected) > 1400:
        rejected = rejected[:1397] + "..."

    has_prior_workspace_call = _has_workspace_tool_call_history(messages)
    root_workdir_repair = bool(_ROOT_WORKDIR_TEXT_PATTERN.search(str(assistant_text or "")))
    prior_history_rule = (
        "A prior workspace client tool call/result is already present in the conversation. "
        "That proves the client tool is exposed and executable in this session. Continue using the declared "
        "client tools as needed; do not claim that exec_command or the local execution tool is unavailable. "
        "Do not claim that the workspace is unmounted merely because the browser itself cannot see it. "
        if has_prior_workspace_call
        else ""
    )

    system = (
        "You are the reasoning backend for a local coding client. The declared client tools are real. "
        "The web page itself has no filesystem access, but the client tools DO execute on the user's machine "
        "under the client's sandbox and approval policy. Browser-visible filesystem state is not authoritative. "
        "Never infer that a local workspace is unmounted, unavailable, or missing merely because the web page "
        "cannot see it. The authoritative way to inspect the workspace is to call a declared client tool. "
        + prior_history_rule
        + f"The current request explicitly declares these workspace tool names: {declared_names}. "
        "This declaration is authoritative for tool availability in this request. "
        + f"For a local workspace task, call {preferred_name} before claiming that a path or file is unavailable. "
        "For exec_command, shell_command, or local_shell, OMIT the workdir field unless the user explicitly asks to "
        "change the working directory. The client's current turn cwd is authoritative. Never use '/' as a default, "
        "fallback, guessed, or placeholder workdir. If the task wants the current workspace, omit workdir entirely. "
        "For inspection tasks, a minimal first command such as pwd plus a directory listing is appropriate; then "
        "read the requested file with the same client tool. After a successful read, continue with the requested "
        "edit and test instead of stopping at an explanation. Do not ask the user to upload a file and do not give "
        "commands for the user to run manually when a declared client tool can perform the action. "
        "Only report a missing path, permission error, or failed test after an actual client tool result says so. "
        "Return exactly one complete <adapter_calls> root when calling tools. Put the tool name in the call name "
        "attribute and put one JSON object inside <arguments encoding=\"json\"><![CDATA[...]]></arguments>. "
        "Use only fields permitted by the declared tool schema. Do not use markdown fences. Do not invent tool results.\n\n"
        "AVAILABLE CLIENT WORKSPACE TOOLS:\n"
        f"{tool_defs}"
    )

    repeated = attempt > 1
    if root_workdir_repair:
        correction = (
            "The previous client tool call incorrectly overrode the Codex turn working directory with workdir='/' "
            "even though the user did not request filesystem root. Reissue the same intended client tool call without "
            "the workdir field so Codex inherits the current turn cwd. Do not guess an absolute replacement path."
        )
        if repeated:
            correction += (
                " This is a repeated root-workdir error. The corrected tool call must omit workdir entirely."
            )
        action = f"Call {preferred_name} again now. Preserve the intended command and omit workdir. Return only the corrected tool-call output."
    elif has_prior_workspace_call:
        correction = (
            "The previous reply contradicted the existing client tool history by claiming that the client execution "
            "tool or mounted local workspace was unavailable. Correct that contradiction now."
        )
        if repeated:
            correction += (
                " This is a repeated contradiction. The current request still explicitly declares the workspace "
                "tool, and prior history proves that the client already executed it. Do not discuss whether the tool "
                "exists or is exposed."
            )
        action = f"Continue the task by calling {preferred_name} again as needed. Return only the corrected tool-call output."
    else:
        correction = (
            "The previous reply incorrectly treated the browser's lack of direct filesystem visibility as evidence "
            "that the local coding client had no mounted workspace. Correct that behavior now."
        )
        if repeated:
            correction += (
                " This is a repeated contradiction. Do not answer with tool-availability commentary; use the declared "
                "client tool now."
            )
        action = f"Call {preferred_name} now to inspect the actual client workspace. Return only the corrected tool-call output."

    user = (
        "[Client Workspace Repair]\n"
        f"Attempt: {attempt}/{total_attempts}\n"
        f"{correction}\n\n"
        "Original user request:\n"
        f"{user_request}\n\n"
        "Rejected reply:\n"
        f"{rejected}\n\n"
        f"{action}"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


__all__ = [
    "build_client_workspace_repair_messages",
    "has_client_workspace_tools",
    "has_suspicious_root_workdir_tool_call",
    "looks_like_client_access_refusal",
    "looks_like_local_workspace_request",
    "looks_like_post_tool_unavailable_claim",
    "should_repair_client_workspace_refusal",
    "user_explicitly_requested_root_workdir",
]
