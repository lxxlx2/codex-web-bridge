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

# Only the V2 affinity adapter creates this private snapshot from its hydrated
# Responses history. It is carried on the current tool-result delta for local
# policy decisions and is never serialized into the browser prompt.
_ACCEPTANCE_STATE_KEY = "_uwa_synthetic_acceptance_state"
_ACCEPTANCE_PATHS = {
    "CONTEXT_PASS": "context/result.txt",
    "LARGE_CONTEXT_PASS": "large_context/result.txt",
}

_WORKSPACE_REQUEST_PATTERNS = (
    re.compile(r"\bworkspace\b", re.IGNORECASE),
    re.compile(r"\brepo(?:sitory)?\b", re.IGNORECASE),
    re.compile(r"\blocal\s+(?:file|directory|project|workspace)\b", re.IGNORECASE),
    re.compile(r"\b(?:read|inspect|open|edit|modify|fix|patch|test|run)\b.{0,80}\b(?:file|code|test|project|repo)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:^|[\s/])[^\s/]+\.(?:py|js|jsx|ts|tsx|java|kt|kts|cs|cpp|cc|c|h|hpp|go|rs|rb|php|swift|sh|zsh|bash|toml|yaml|yml|json|md)(?:\b|$)", re.IGNORECASE),
    re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\)", re.IGNORECASE),
    re.compile(r"\b(?:exec_command|shell_command|local_shell|apply_patch|write_stdin)\b", re.IGNORECASE),
    re.compile(r"\b(?:context|large_context)/result\.txt\b", re.IGNORECASE),
    re.compile(r"\b(?:CONTEXT_PASS|LARGE_CONTEXT_PASS)\b"),
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
    re.compile(
        r"(?:当前(?:运行|执行)?环境|当前(?:这个)?会话).{0,80}"
        r"(?:无法|不能|不可).{0,30}(?:访问|读取|写入)"
        r".{0,120}(?:/Users/|/home/|[A-Za-z]:\\|workspace|工作区|large_context|context)",
        re.IGNORECASE | re.DOTALL,
    ),
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

    # current_environment_no_callable_workspace_tool:
    # Real ChatGPT Web wording observed by the standalone S3 live gate before
    # the first client tool call has occurred.
    re.compile(
        r"(?:当前环境|当前这个会话|当前会话环境).{0,60}"
        r"(?:没有|未).{0,35}(?:可调用的?\s*)?"
        r"(?:exec_command|shell_command|local_shell|apply_patch|write_stdin)"
        r".{0,50}(?:客户端函数|客户端工具|本地执行工具|执行工具|函数|工具)",
        re.IGNORECASE | re.DOTALL,
    ),

    # recursive_compaction_current_session_tool_entry_absent:
    # Live S3 wording after recursive compaction: the model remembers the
    # durable state and pending workspace action but incorrectly says the
    # current chat/session cannot turn the declared client tool into an
    # actually callable execution entry.
    re.compile(
        r"(?:当前(?:这个)?(?:ChatGPT\s*)?会话|当前环境|当前这个会话)"
        r".{0,140}(?:无法|不能|没有|并无|不存在)"
        r".{0,140}(?:exec_command|shell_command|local_shell|apply_patch|write_stdin)"
        r".{0,100}(?:实际可调用|可调用|执行入口|客户端工具|本地工具|执行工具)",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"(?:exec_command|shell_command|local_shell|apply_patch|write_stdin)"
        r".{0,140}(?:无法|不能|没有|并无|不存在)"
        r".{0,140}(?:实际可调用|可调用|执行入口|当前(?:ChatGPT\s*)?会话|当前会话)",
        re.IGNORECASE | re.DOTALL,
    ),

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
    re.compile(r"(?:当前(?:这个)?会话|当前环境).{0,80}(?:没有|未|缺少).{0,40}(?:exec_command|shell_command|local_shell|apply_patch|write_stdin|本地执行工具|执行工具|客户端工具)"),
    re.compile(r"(?:当前|这轮|现在)?.{0,30}(?:实际)?(?:可调用|可用|提供|暴露)(?:的)?.{0,30}(?:客户端)?工具.{0,50}(?:没有|不存在|不包含|不含|找不到).{0,35}(?:名为\s*)?(?:exec_command|shell_command|本地执行工具|执行工具|客户端工具)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:当前|这轮|现在)?.{0,30}(?:实际)?(?:可调用|可用)(?:工具|工具列表|tool list).{0,60}(?:没有|不存在|不包含|不含).{0,35}(?:exec_command|shell_command|local_shell|apply_patch|write_stdin)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:无法|不能).{0,40}(?:真实|实际).{0,30}(?:写入|修改|运行|测试).{0,100}(?:因为|由于).{0,80}(?:工具|exec_command).{0,50}(?:没有|未|不可用|未暴露)"),
    re.compile(r"(?:当前(?:这轮|这个)?(?:实际)?可调用的执行环境|当前(?:这个)?会话(?:实际)?可用的(?:执行环境|文件系统)|当前环境).{0,120}(?:没有|未).{0,30}(?:挂载|映射).{0,100}(?:本机|本地|工作区|目录|路径|/Users/|/home/)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:没有|未).{0,30}(?:挂载|映射).{0,100}(?:本机|本地|工作区|/Users/|/home/).{0,120}(?:无法|不能).{0,50}(?:真实|实际).{0,30}(?:写入|修改|运行|测试)", re.IGNORECASE | re.DOTALL),
    # post_tool_readback_refusal:
    # A real workspace tool has already executed successfully, but the model
    # subsequently claims it cannot use the same declared tool to perform the
    # required readback / verification step.
    re.compile(
        r"(?:exec_command|shell_command|local_shell|客户端工具|执行工具|本地执行工具)"
        r".{0,140}(?:无法|不能|不可|不能够|cannot|can't|unable)"
        r".{0,100}(?:读取|回读|确认|验证|检查|read|read back|verify|confirm|check)",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"(?:无法|不能|不可|不能够|cannot|can't|unable)"
        r".{0,100}(?:读取|回读|确认|验证|检查|read|read back|verify|confirm|check)"
        r".{0,140}(?:exec_command|shell_command|local_shell|客户端工具|执行工具|本地执行工具)",
        re.IGNORECASE | re.DOTALL,
    ),
    # post_tool_readback_refusal_prefix_tool_readback:
    # Live Gate B wording after successful workspace validation + write:
    # "无法完成所要求的本地 exec_command 读取校验，因此不能据实回复 CONTEXT_PASS。"
    # The inability clause precedes the tool name, which in turn precedes the
    # readback verb, so the two historical readback orderings do not match.
    re.compile(
        r"(?:无法|不能|不可|不能够|cannot|can't|unable)"
        r".{0,100}(?:完成|执行|进行|perform|complete)?"
        r".{0,100}(?:exec_command|shell_command|local_shell|客户端工具|执行工具|本地执行工具)"
        r".{0,100}(?:读取|回读|确认|验证|检查|read|read back|verify|confirm|check)",
        re.IGNORECASE | re.DOTALL,
    ),
    # post_tool_current_toolset_absent:
    # Live post-compaction wording after a successful write call:
    # "无法执行该 exec_command 调用，因为当前实际可用工具集中没有这个客户端工具。"
    # The call name appears before the "toolset has no such client tool"
    # clause, so older availability patterns did not match it.
    re.compile(
        r"(?:无法|不能).{0,40}"
        r"(?:exec_command|shell_command|local_shell|apply_patch|write_stdin)"
        r".{0,80}(?:调用|执行)?"
        r".{0,100}(?:当前|这轮|现在).{0,40}(?:实际)?(?:可用|可调用)?工具(?:集|集合|列表|toolset|tool list)?"
        r".{0,80}(?:没有|不存在|不包含|不含).{0,50}(?:这个|该|对应的)?(?:客户端)?工具",
        re.IGNORECASE | re.DOTALL,
    ),
    # post_tool_this_round_no_callable_client_tool:
    # Live restart-resume wording after prior successful exec_command calls:
    # "当前这一轮没有可调用的客户端 exec_command ... 缺少 ... 最终读取确认"
    re.compile(
        r"(?:当前(?:这)?一轮|这一轮|本轮|这轮)"
        r".{0,50}(?:没有|不存在|不具备|缺少)"
        r".{0,40}(?:可调用的?|可用的?)"
        r".{0,30}(?:客户端)?"
        r"(?:exec_command|shell_command|local_shell|apply_patch|write_stdin)"
        r".{0,180}(?:读取|回读|确认|验证|read|read back|verify|confirm)",
        re.IGNORECASE | re.DOTALL,
    ),
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


def _specific_required_workspace_tool_name(
    tool_choice: Any,
    tools: List[Dict[str, Any]],
) -> str:
    """Return a specifically required declared workspace tool, if any.

    Only an explicit named tool choice is authoritative here. A generic
    tool_choice='required' can refer to any declared tool and must not be
    coerced into a workspace-tool repair.
    """

    if not isinstance(tool_choice, dict):
        return ""

    function_data = (
        tool_choice.get("function")
        if isinstance(tool_choice.get("function"), dict)
        else {}
    )
    name = str(
        function_data.get("name")
        or tool_choice.get("name")
        or ""
    ).strip()

    if name not in _WORKSPACE_TOOL_PRIORITY:
        return ""

    declared = {
        _tool_name(item)
        for item in tools or []
        if _tool_name(item)
    }
    return name if name in declared else ""


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


def _message_content_text(message: Dict[str, Any]) -> str:
    if not isinstance(message, dict):
        return ""

    content = message.get("content")

    if isinstance(content, str):
        return content

    try:
        return json.dumps(
            content,
            ensure_ascii=False,
        )
    except Exception:
        return str(content or "")


def _latest_user_is_function_output_fallback(
    messages: List[Dict[str, Any]],
) -> bool:
    text = _latest_user_text(
        messages
    ).lstrip()

    return text.startswith(
        "[Function Call Output"
    )


def _latest_user_is_generated_function_output_fallback(
    messages: List[Dict[str, Any]],
) -> bool:
    """Recognize only bridge-generated Responses tool-result fallbacks."""

    for message in reversed(messages or []):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip().lower()
        if role != "user":
            continue
        return message.get("_uwa_function_output_fallback") is True

    return False


def _latest_private_compacted_continuation_text(
    messages: List[Dict[str, Any]],
) -> str:
    """Return compacted continuation carried only as internal bridge metadata."""

    for message in reversed(messages or []):
        if not isinstance(message, dict):
            continue
        value = message.get("_uwa_compacted_continuation_context")
        if not isinstance(value, str):
            continue
        text = value.strip()
        if "[Compacted prior context]" in text:
            if len(text) > 3200:
                text = text[:3197] + "..."
            return text

    return ""


def _looks_like_compacted_workspace_continuation(
    messages: List[Dict[str, Any]],
) -> bool:
    """Recover unresolved workspace intent after compaction removed tool history.

    A post-compaction continuation is not guaranteed to present the latest
    client-tool result as the newest user-shaped message. In particular, Codex
    may compact again between a successful workspace-validation call and the
    remaining write/read steps. The compacted assistant state is therefore the
    durable source of active intent.

    Prefer the ACTIVE CONTINUATION STATE section when present so completed
    historical workspace actions do not become actionable again. Legacy
    compaction summaries without structured sections fall back to the full
    compacted text.
    """

    active_header = "[ACTIVE CONTINUATION STATE]"

    private_context = _latest_private_compacted_continuation_text(
        messages
    )
    if private_context:
        candidate = private_context
        if active_header in private_context:
            candidate = private_context.split(
                active_header,
                1,
            )[1]
        return any(
            pattern.search(candidate)
            for pattern
            in _WORKSPACE_REQUEST_PATTERNS
        )

    for message in reversed(
        messages or []
    ):
        if not isinstance(message, dict):
            continue

        role = str(
            message.get("role") or ""
        ).strip().lower()

        if role != "assistant":
            continue

        text = _message_content_text(
            message
        )

        if (
            "[Compacted prior context]"
            not in text
        ):
            continue

        candidate = text

        if active_header in text:
            candidate = text.split(
                active_header,
                1,
            )[1]

        return any(
            pattern.search(candidate)
            for pattern
            in _WORKSPACE_REQUEST_PATTERNS
        )

    return False


def _latest_compacted_continuation_text(
    messages: List[Dict[str, Any]],
) -> str:
    """Return the newest compacted continuation state, bounded for repair prompts."""

    private_context = _latest_private_compacted_continuation_text(
        messages
    )
    if private_context:
        return private_context

    for message in reversed(messages or []):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").strip().lower() != "assistant":
            continue

        text = _message_content_text(message)
        if "[Compacted prior context]" not in text:
            continue

        value = text.strip()
        if len(value) > 3200:
            value = value[:3197] + "..."
        return value

    return ""


def looks_like_client_access_refusal(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return any(pattern.search(value) for pattern in _REFUSAL_PATTERNS)


_MISSING_TASK_CLARIFICATION_PATTERNS = (
    re.compile(
        r"(?:请|麻烦)?(?:直接|继续|重新|再)?(?:发送|提供|给出|告诉我).{0,60}"
        r"(?:具体任务|任务|验证步骤|操作步骤|需要我执行的)",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"(?:please\s+)?(?:send|provide|give|tell me).{0,60}"
        r"(?:the\s+)?(?:concrete|specific|next|remaining)?\s*"
        r"(?:task|steps?|verification steps?|action)",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"(?:what|which).{0,50}(?:task|step|action).{0,50}"
        r"(?:should|do you want|need me to)",
        re.IGNORECASE | re.DOTALL,
    ),
    # post_compaction_no_new_concrete_task:
    # Live S3 wording after successful workspace validation. The model retained
    # the exact durable token but incorrectly treated the current tool-result
    # continuation as if no actionable task remained:
    # "当前消息没有包含新的具体执行任务。"
    #
    # This matcher is only actionable inside
    # should_repair_client_workspace_refusal when authoritative compacted
    # workspace intent/provenance is also present, so ordinary conversational
    # acknowledgements are not turned into workspace actions.
    re.compile(
        r"(?:当前|这条|本轮|这轮)?(?:消息|请求|输入)"
        r".{0,40}(?:没有|未|并未|不包含)"
        r".{0,40}(?:包含|提供|给出|指定)?"
        r".{0,40}(?:新的?)?(?:具体)?(?:执行)?(?:任务|操作|步骤)",
        re.IGNORECASE | re.DOTALL,
    ),
    # post_compaction_no_new_acceptance_instruction:
    # Live S3 wording after successful post-compaction workspace validation:
    # "当前消息里没有新的验收命令、目标文件或预期输出，因此没有可执行的下一步。"
    # The model retained the exact durable token but incorrectly ignored the
    # unresolved ACTIVE CONTINUATION STATE. This matcher is only actionable
    # when compacted workspace intent/provenance is authoritative.
    re.compile(
        r"(?:当前|这条|本轮|这轮)?(?:消息|请求|输入)"
        r".{0,40}(?:没有|未|并未|不包含)"
        r".{0,60}(?:新的?)?"
        r"(?:验收命令|验证命令|目标文件|预期输出)"
        r".{0,120}(?:没有|无|不存在)"
        r".{0,40}(?:可执行的?)?(?:下一步|后续步骤|操作)",
        re.IGNORECASE | re.DOTALL,
    ),
)


def looks_like_missing_task_clarification(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return any(
        pattern.search(value)
        for pattern in _MISSING_TASK_CLARIFICATION_PATTERNS
    )


_COMPACTED_STATE_ONLY_ACK_PATTERNS = (
    re.compile(
        r"(?:当前)?上下文.{0,20}(?:已|已经)?恢复"
        r".{0,80}(?:精确值|精确令牌|需要保留|继续保留|remember|retained)"
        r".{0,80}",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"(?:已|已经)?(?:续接|承接|恢复).{0,20}(?:当前)?(?:状态|上下文)"
        r".{0,80}(?:保留|记住|恢复).{0,40}(?:精确值|精确令牌|精确测试值)",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"(?:context|state).{0,30}(?:restored|recovered)"
        r".{0,100}(?:exact|durable).{0,40}(?:value|token|state)"
        r".{0,100}",
        re.IGNORECASE | re.DOTALL,
    ),
)


def looks_like_compacted_state_only_acknowledgement(text: str) -> bool:
    """Detect a final that merely echoes recovered durable state and stops."""

    value = str(text or "").strip()
    if not value:
        return False
    return any(
        pattern.search(value)
        for pattern in _COMPACTED_STATE_ONLY_ACK_PATTERNS
    )


def looks_like_post_tool_unavailable_claim(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return any(pattern.search(value) for pattern in _POST_TOOL_UNAVAILABLE_PATTERNS)


def _tool_result_exit_zero(message: Dict[str, Any]) -> bool:
    if not isinstance(message, dict):
        return False
    role = str(message.get("role") or "").strip().lower()
    if role not in {"tool", "function"}:
        return False

    text = _message_content_text(message)
    if not text:
        return False

    patterns = (
        r"Process exited with code 0\b",
        r"exit(?:ed)?(?:\s+with)?(?:\s+code)?\s*[:=]?\s*0\b",
        r"\"exit_code\"\s*:\s*0\b",
    )
    return any(
        re.search(pattern, text, re.IGNORECASE)
        for pattern in patterns
    )


def _successful_acceptance_workspace_validation_observed(
    messages: List[Dict[str, Any]],
    *,
    result_path: str | None = None,
) -> bool:
    """Return True only for a real successful acceptance workspace probe."""

    calls: Dict[str, str] = {}

    for message in messages or []:
        if not isinstance(message, dict):
            continue

        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            for item in tool_calls:
                if not isinstance(item, dict):
                    continue
                if _tool_name(item) not in _EXEC_LIKE_TOOLS:
                    continue
                call_id = str(item.get("id") or "").strip()
                args = _decode_tool_arguments(item)
                command = str(args.get("cmd") or args.get("command") or "").strip()
                if call_id and command:
                    calls[call_id] = command

        role = str(message.get("role") or "").strip().lower()
        if role not in {"tool", "function"}:
            continue

        call_id = str(
            message.get("tool_call_id")
            or message.get("call_id")
            or ""
        ).strip()
        command = calls.get(call_id, "")

        if not command or not _tool_result_exit_zero(message):
            continue

        common_required = (
            "pwd",
            "test -f .uwa_codex_acceptance",
        )
        if result_path:
            acceptance_dirs = (
                f"test -d {result_path.split('/', 1)[0]}",
            )
        else:
            acceptance_dirs = (
                "test -d large_context",
                "test -d context",
            )
        if (
            all(
                fragment in command
                for fragment in common_required
            )
            and any(
                fragment in command
                for fragment in acceptance_dirs
            )
        ):
            return True

    state = _private_acceptance_state(messages)
    return bool(
        state
        and state["validated"]
        and (result_path is None or state["result_path"] == result_path)
    )


def looks_like_false_acceptance_workspace_mismatch(
    assistant_text: str,
    messages: List[Dict[str, Any]],
) -> bool:
    return (
        str(assistant_text or "").strip()
        == "ACCEPTANCE_WORKSPACE_MISMATCH"
        and _successful_acceptance_workspace_validation_observed(
            messages
        )
    )


def _successful_workspace_commands(
    messages: List[Dict[str, Any]],
) -> List[str]:
    """Return completed exit-zero exec-like commands paired with real tool results."""

    calls: Dict[str, str] = {}
    successful: List[str] = []

    for message in messages or []:
        if not isinstance(message, dict):
            continue

        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            for item in tool_calls:
                if not isinstance(item, dict):
                    continue
                if _tool_name(item) not in _EXEC_LIKE_TOOLS:
                    continue
                call_id = str(item.get("id") or "").strip()
                args = _decode_tool_arguments(item)
                command = str(
                    args.get("cmd")
                    or args.get("command")
                    or ""
                ).strip()
                if call_id and command:
                    calls[call_id] = command

        role = str(message.get("role") or "").strip().lower()
        if role not in {"tool", "function"}:
            continue

        call_id = str(
            message.get("tool_call_id")
            or message.get("call_id")
            or ""
        ).strip()
        command = calls.get(call_id, "")
        if command and _tool_result_exit_zero(message):
            successful.append(command)

    return successful


def _acceptance_success_contract(
    assistant_text: str,
    messages: List[Dict[str, Any]],
) -> tuple[str, str] | None:
    """Return the exact synthetic success marker/result path requested by the user."""

    contract = _acceptance_contract_from_messages(messages)
    if contract is None or str(assistant_text or "").strip() != contract[0]:
        return None
    return contract


def _private_acceptance_state(
    messages: List[Dict[str, Any]],
) -> Dict[str, Any] | None:
    """Read only a well-formed adapter-generated synthetic acceptance snapshot."""

    for message in reversed(messages or []):
        if not isinstance(message, dict):
            continue
        state = message.get(_ACCEPTANCE_STATE_KEY)
        if not isinstance(state, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        if (
            role not in {"tool", "function"}
            and message.get("_uwa_function_output_fallback") is not True
        ):
            return None
        marker = state.get("marker")
        if _ACCEPTANCE_PATHS.get(marker) != state.get("result_path"):
            return None
        if any(
            type(state.get(key)) is not bool
            for key in ("validated", "written", "readback")
        ):
            return None
        if not state["validated"] or (state["readback"] and not state["written"]):
            return None
        return state
    return None



def _acceptance_contract_from_messages(
    messages: List[Dict[str, Any]],
) -> tuple[str, str] | None:
    """Return one unambiguous synthetic acceptance contract from request history."""

    searchable: List[str] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        searchable.append(_message_content_text(message))
        private = message.get("_uwa_compacted_continuation_context")
        if isinstance(private, str):
            searchable.append(private)

    combined = "\n".join(searchable)
    matches = [
        (marker, result_path)
        for marker, result_path in _ACCEPTANCE_PATHS.items()
        if (
            re.search(
                rf"(?<![A-Z0-9_]){re.escape(marker)}(?![A-Z0-9_])",
                combined,
            )
            and result_path in combined
        )
    ]
    private = _private_acceptance_state(messages)
    if private is not None:
        contract = (private["marker"], private["result_path"])
        return contract if not matches or matches == [contract] else None
    return matches[0] if len(matches) == 1 else None


def _acceptance_effect_progress(
    messages: List[Dict[str, Any]],
    result_path: str,
) -> tuple[bool, bool]:
    """Return successful write and later separate readback state for one result path."""

    commands = _successful_workspace_commands(messages)
    write_indexes = [
        index
        for index, command in enumerate(commands)
        if _command_writes_result_path(command, result_path)
    ]
    if not write_indexes:
        state = _private_acceptance_state(messages)
        if state is not None and state["result_path"] == result_path:
            return state["written"], state["readback"]
        return False, False

    last_write_index = write_indexes[-1]
    readback_after_write = any(
        index > last_write_index
        and _command_reads_result_path(command, result_path)
        for index, command in enumerate(commands)
    )
    state = _private_acceptance_state(messages)
    if state is not None and state["result_path"] == result_path:
        return state["written"], state["readback"]
    return True, readback_after_write


def _acceptance_state_from_history(
    messages: List[Dict[str, Any]],
) -> Dict[str, Any] | None:
    """Summarize only proven synthetic effects from the hydrated tool history."""

    contract = _acceptance_contract_from_messages(messages)
    if contract is None:
        return None
    marker, result_path = contract
    if not _successful_acceptance_workspace_validation_observed(
        messages,
        result_path=result_path,
    ):
        return None
    written, readback = _acceptance_effect_progress(messages, result_path)
    return {
        "marker": marker,
        "result_path": result_path,
        "validated": True,
        "written": written,
        "readback": readback,
    }


def _looks_like_acceptance_step_execution_stall(
    assistant_text: str,
    marker: str,
) -> bool:
    """Match a narrow synthetic step-stall final tied to the requested PASS marker."""

    value = str(assistant_text or "").strip()
    if not value:
        return False

    marker_pattern = (
        rf"(?<![A-Z0-9_]){re.escape(marker)}(?![A-Z0-9_])"
    )
    if re.search(marker_pattern, value) is None:
        return False

    return re.search(
        r"(?:第二步|第三步|step\s*(?:2|3))"
        r".{0,60}(?:未能|无法|不能|could\s+not|couldn't|unable)"
        r".{0,100}(?:exec_command|shell_command|local_shell)"
        r".{0,80}(?:执行|调用|run|execute|call)"
        r".{0,120}(?:不能|无法|不可|cannot|can't|could\s+not|unable)"
        r".{0,60}(?:回复|返回|reply|return)",
        value,
        re.IGNORECASE | re.DOTALL,
    ) is not None


def _looks_like_acceptance_capability_refusal(
    assistant_text: str,
    marker: str,
) -> bool:
    """Detect capability/workspace refusal inside a proven synthetic acceptance."""

    value = str(assistant_text or "").strip()
    if not value:
        return False

    marker_pattern = (
        rf"(?<![A-Z0-9_]){re.escape(marker)}(?![A-Z0-9_])"
    )
    if re.search(marker_pattern, value) is None:
        return False

    tool_unavailable = re.search(
        r"(?:没有|缺少|不存在|无|not\s+have|without|no)"
        r".{0,50}(?:实际)?(?:可调用|可用|callable|available)"
        r".{0,50}(?:exec_command|shell_command|local_shell|客户端工具|执行工具)"
        r"|(?:exec_command|shell_command|local_shell|客户端工具|执行工具)"
        r".{0,80}(?:不可用|无法调用|不能调用|not\s+callable|unavailable|not\s+available)",
        value,
        re.IGNORECASE | re.DOTALL,
    ) is not None

    workspace_unavailable = re.search(
        r"(?:无法|不能|不可|cannot|can't|unable)"
        r".{0,40}(?:访问|读取|写入|access|read|write)"
        r".{0,120}(?:/Users/|/home/|[A-Za-z]:\\|workspace|工作区|large_context|context)",
        value,
        re.IGNORECASE | re.DOTALL,
    ) is not None

    return tool_unavailable or workspace_unavailable


def _looks_like_acceptance_effect_step_stall(
    assistant_text: str,
    marker: str,
    *,
    write_observed: bool,
    readback_observed: bool,
) -> bool:
    """Use proven acceptance progress to interpret a blocked numbered step."""

    value = str(assistant_text or "").strip()
    if not value or readback_observed:
        return False

    marker_pattern = (
        rf"(?<![A-Z0-9_]){re.escape(marker)}(?![A-Z0-9_])"
    )
    if re.search(marker_pattern, value) is None:
        return False

    withheld_success = re.search(
        r"(?:不能|无法|不可|cannot|can't|unable)"
        r".{0,60}(?:回复|返回|reply|return)",
        value,
        re.IGNORECASE | re.DOTALL,
    ) is not None
    if not withheld_success:
        return False

    blocked = (
        r"(?:无法|不能|未能|不可|cannot|can't|could\s+not|unable)"
    )
    if write_observed:
        return (
            re.search(
                rf"(?:第三步|step\s*3).{{0,120}}{blocked}",
                value,
                re.IGNORECASE | re.DOTALL,
            )
            is not None
            and re.search(
                r"(?:验证|校验|字节|readback|verify|verification|byte)",
                value,
                re.IGNORECASE | re.DOTALL,
            )
            is not None
        )

    return (
        re.search(
            rf"(?:第二步|step\s*2).{{0,120}}{blocked}",
            value,
            re.IGNORECASE | re.DOTALL,
        )
        is not None
        and re.search(
            r"(?:写入|执行|完成|write|execute|complete)",
            value,
            re.IGNORECASE | re.DOTALL,
        )
        is not None
    )


def looks_like_incomplete_acceptance_continuation(
    assistant_text: str,
    messages: List[Dict[str, Any]],
) -> bool:
    """Detect a narrowly unfinished synthetic acceptance continuation."""

    contract = _acceptance_contract_from_messages(messages)
    if contract is None:
        return False

    marker, result_path = contract
    if not _successful_acceptance_workspace_validation_observed(
        messages,
        result_path=result_path,
    ):
        return False

    write_observed, readback_observed = _acceptance_effect_progress(
        messages,
        result_path,
    )
    if write_observed and readback_observed:
        return False

    value = str(assistant_text or "").strip()
    # Once a paired validation and write have succeeded, every text-only
    # continuation is premature: the separate byte readback is still pending.
    # This rule is limited to the two synthetic acceptance contracts above.
    if write_observed:
        return True
    return (
        value == "ACCEPTANCE_INCOMPLETE"
        or _looks_like_acceptance_step_execution_stall(
            value,
            marker,
        )
        or _looks_like_acceptance_capability_refusal(
            value,
            marker,
        )
        or _looks_like_acceptance_effect_step_stall(
            value,
            marker,
            write_observed=write_observed,
            readback_observed=readback_observed,
        )
    )


def _command_writes_result_path(command: str, result_path: str) -> bool:
    value = str(command or "")
    if result_path not in value:
        return False
    return any(
        marker in value
        for marker in (
            ">",
            "write_text",
            "write_bytes",
            "tee ",
        )
    )


def _command_reads_result_path(command: str, result_path: str) -> bool:
    value = str(command or "")
    if result_path not in value:
        return False
    return any(
        marker in value
        for marker in (
            "read_bytes",
            "xxd ",
            "od ",
            "hexdump ",
        )
    )


def _completed_acceptance_contract(
    messages: List[Dict[str, Any]],
) -> tuple[str, str] | None:
    """Return the synthetic acceptance contract only after all required effects."""

    contract = _acceptance_contract_from_messages(messages)
    if contract is None:
        return None

    marker, result_path = contract
    if not _successful_acceptance_workspace_validation_observed(
        messages,
        result_path=result_path,
    ):
        return None

    write_observed, readback_observed = _acceptance_effect_progress(
        messages,
        result_path,
    )
    if not (write_observed and readback_observed):
        return None

    return marker, result_path


def has_redundant_acceptance_tool_call_after_completion(
    messages: List[Dict[str, Any]],
    parsed: Dict[str, Any],
) -> bool:
    """Reject extra workspace tool calls once a synthetic acceptance is complete."""

    if _completed_acceptance_contract(messages) is None:
        return False

    for tool_call in parsed.get("tool_calls") or []:
        if not isinstance(tool_call, dict):
            continue
        if _tool_name(tool_call) in _EXEC_LIKE_TOOLS:
            return True

    return False


def looks_like_acceptance_completion_without_exact_sentinel(
    assistant_text: str,
    messages: List[Dict[str, Any]],
) -> bool:
    """Require the exact requested success sentinel after all effects complete."""

    contract = _completed_acceptance_contract(messages)
    if contract is None:
        return False

    marker, _result_path = contract
    return str(assistant_text or "").strip() != marker


def looks_like_premature_acceptance_success(
    assistant_text: str,
    messages: List[Dict[str, Any]],
) -> bool:
    """Detect a synthetic PASS returned after validation but before required effects.

    This is deliberately limited to the repository's acceptance sentinels and
    real paired client-tool history. It does not infer generic business-task
    correctness from arbitrary shell commands.
    """

    contract = _acceptance_success_contract(
        assistant_text,
        messages,
    )
    if contract is None:
        return False

    if not _successful_acceptance_workspace_validation_observed(
        messages
    ):
        return False

    _marker, result_path = contract
    written, readback = _acceptance_effect_progress(messages, result_path)
    return not (written and readback)


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
        return bool(
            has_redundant_acceptance_tool_call_after_completion(
                messages,
                parsed,
            )
            or has_suspicious_root_workdir_tool_call(
                messages,
                parsed,
            )
        )

    if str(parsed.get("mode") or "").strip().lower() != "final":
        return False

    if looks_like_acceptance_completion_without_exact_sentinel(
        assistant_text,
        messages,
    ):
        return True

    # A specific required workspace tool is protocol-level evidence that this
    # turn must call that client tool. If the model returns only final text and
    # no parsed tool call, repair the contradiction directly instead of relying
    # on request/refusal wording regexes. This remains authoritative even after
    # earlier tool history. Generic tool_choice='required' intentionally does
    # not enter this path.
    if _specific_required_workspace_tool_name(tool_choice, tools):
        return True

    # The current request's declared client-tool schema is itself authoritative
    # evidence that those tools are exposed to the Codex client. Recursive
    # compaction can legitimately remove the immediately preceding
    # function_call/function_call_output items and private provenance markers.
    # Do not let that lossy history shape turn an explicit "exec_command is not
    # exposed/available in this environment" claim into an accepted final
    # answer. This branch is intentionally limited to the strong post-tool
    # unavailability patterns and still respects tool_choice='none' above.
    if looks_like_post_tool_unavailable_claim(assistant_text):
        return True

    compacted_workspace_request = (
        _looks_like_compacted_workspace_continuation(
            messages
        )
    )

    has_history = _has_tool_history(messages)
    function_output_fallback = (
        _latest_user_is_function_output_fallback(
            messages
        )
    )
    generated_function_output_fallback = (
        _latest_user_is_generated_function_output_fallback(
            messages
        )
    )
    workspace_tool_provenance = (
        _has_workspace_tool_call_history(
            messages
        )
    )
    if (
        not workspace_tool_provenance
        and generated_function_output_fallback
    ):
        # This private marker is attached only while normalizing an actual
        # Responses function_call_output/tool_result that cannot be paired with
        # its assistant function_call after compaction. It is internal
        # provenance, not browser-visible prompt text, so it is authoritative
        # even when affinity sends only the current delta and the compacted
        # summary remains solely in the already-open ChatGPT conversation.
        workspace_tool_provenance = True
    elif (
        not workspace_tool_provenance
        and function_output_fallback
        and compacted_workspace_request
    ):
        # Backward-compatible path for older in-memory normalized messages that
        # predate the private provenance marker.
        workspace_tool_provenance = True

    if looks_like_incomplete_acceptance_continuation(
        assistant_text,
        messages,
    ):
        return True

    if (
        has_history
        and looks_like_premature_acceptance_success(
            assistant_text,
            messages,
        )
    ):
        return True

    if (
        has_history
        and looks_like_false_acceptance_workspace_mismatch(
            assistant_text,
            messages,
        )
    ):
        return True

    if (
        has_history
        or generated_function_output_fallback
        or (
            function_output_fallback
            and compacted_workspace_request
        )
    ):
        # Once a workspace tool has really appeared in the conversation, an
        # explicit later claim that the same declared tool is absent is a direct
        # contradiction. Do not depend on the latest user-shaped message still
        # looking like the original coding request: Codex follow-up turns often
        # encode tool output as the newest user item.
        if (
            workspace_tool_provenance
            and (
                looks_like_post_tool_unavailable_claim(assistant_text)
                or (
                    compacted_workspace_request
                    and looks_like_client_access_refusal(assistant_text)
                )
            )
        ):
            # A real prior client-tool result plus compacted workspace intent
            # proves the client workspace path is actionable. A later claim
            # that the same workspace is inaccessible is therefore a
            # contradiction even when the final wording does not explicitly
            # say that exec_command itself is unavailable.
            return True

        # After recursive compaction the model can retain the exact pending
        # workspace state yet still ask the user to resend "the concrete task"
        # or "verification steps". That is also a contradiction: the pending
        # action is already present in ACTIVE CONTINUATION STATE.
        return bool(
            compacted_workspace_request
            and (
                looks_like_missing_task_clarification(
                    assistant_text
                )
                or looks_like_compacted_state_only_acknowledgement(
                    assistant_text
                )
            )
        )

    local_workspace_request = (
        looks_like_local_workspace_request(
            messages
        )
    )

    if not local_workspace_request:
        local_workspace_request = (
            compacted_workspace_request
        )

    if not local_workspace_request:
        return False

    if looks_like_client_access_refusal(
        assistant_text
    ):
        return True

    return bool(
        compacted_workspace_request
        and (
            looks_like_missing_task_clarification(
                assistant_text
            )
            or looks_like_compacted_state_only_acknowledgement(
                assistant_text
            )
        )
    )


def build_client_workspace_repair_messages(
    *,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    assistant_text: str,
    attempt: int,
    total_attempts: int,
    tool_choice: Any = None,
) -> List[Dict[str, str]]:
    """Build a small corrective prompt without exposing additional local data."""

    workspace_tools = _workspace_tool_defs(tools)
    specifically_required = _specific_required_workspace_tool_name(
        tool_choice,
        tools,
    )
    preferred_name = (
        specifically_required
        or (_tool_name(workspace_tools[0]) if workspace_tools else "exec_command")
    )
    declared_names = [name for name in (_tool_name(item) for item in workspace_tools) if name]
    tool_defs = json.dumps(workspace_tools, ensure_ascii=False, indent=2)
    user_request = _latest_user_text(messages).strip()
    if len(user_request) > 2200:
        user_request = user_request[:2197] + "..."
    rejected = str(assistant_text or "").strip()
    if len(rejected) > 1400:
        rejected = rejected[:1397] + "..."

    compacted_context = _latest_compacted_continuation_text(
        messages
    )
    completed_acceptance = _completed_acceptance_contract(
        messages
    )

    has_prior_workspace_call = (
        _has_workspace_tool_call_history(
            messages
        )
        or _latest_user_is_generated_function_output_fallback(
            messages
        )
        or (
            _latest_user_is_function_output_fallback(
                messages
            )
            and _looks_like_compacted_workspace_continuation(
                messages
            )
        )
    )
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
        "The XML adapter_calls response is the transport that the local client consumes to execute a tool call. "
        "Returning a valid adapter_calls envelope for a declared client tool is the real invocation request; it is "
        "not a fabricated result and does not require the browser UI itself to expose a filesystem control. "
        "Do not wait for the web page to display a local tool before emitting the declared client-tool call. "
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
        "If that JSON contains the literal CDATA terminator ]]>, split it across adjacent CDATA sections as "
        "]]]]><![CDATA[> so the XML remains well-formed and the JSON text is unchanged. "
        "Use only fields permitted by the declared tool schema. Do not use markdown fences. Do not invent tool results.\n\n"
        "AVAILABLE CLIENT WORKSPACE TOOLS:\n"
        f"{tool_defs}"
    )

    repeated = attempt > 1
    if completed_acceptance is not None:
        marker, result_path = completed_acceptance
        correction = (
            "All required synthetic acceptance workspace effects have already completed successfully. "
            f"The existing {result_path} was written and then independently verified with a byte-level "
            "readback after the last successful write. The previous response attempted an extra workspace "
            "tool call or returned descriptive prose after the acceptance was already complete. "
            f"Do not call any client tool again. Do not rewrite {result_path}. Do not perform another "
            "readback. The original acceptance contract now requires only its exact success sentinel."
        )
        if repeated:
            correction += (
                " This completion-contract violation has already repeated. Do not emit another tool call "
                "or explanatory sentence."
            )
        action = (
            f"Reply with exactly {marker} and nothing else. "
            "Do not emit adapter_calls or any other markup."
        )
    elif root_workdir_repair:
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
    elif specifically_required and not looks_like_incomplete_acceptance_continuation(
        assistant_text,
        messages,
    ):
        correction = (
            f"The request-level tool choice explicitly requires {preferred_name}. This is a protocol contract, "
            "not a suggestion. A text-only answer is invalid for this turn. Emit the declared client-tool call "
            "through the adapter_calls transport instead of discussing whether the browser UI exposes the tool."
        )
        if repeated:
            correction += (
                " This required-tool refusal has already repeated. Do not provide any more capability commentary. "
                "The next response must be one executable client-tool call. If the Original user request supplies "
                "the first command to run, preserve that command exactly and omit workdir unless it was explicitly requested."
            )
        action = (
            f"Call {preferred_name} now. "
            f"Return exactly one {preferred_name} call now and no prose. "
            "Use the command/action required by the Original user request. "
            "Do not invent a result; the client will execute the emitted call."
        )
    elif looks_like_incomplete_acceptance_continuation(
        assistant_text,
        messages,
    ):
        contract = _acceptance_contract_from_messages(
            messages
        )
        result_path = (
            contract[1]
            if contract is not None
            else "the acceptance result file"
        )
        write_observed, _readback_observed = _acceptance_effect_progress(
            messages,
            result_path,
        )
        if write_observed:
            correction = (
                "The previous reply stopped the synthetic acceptance request even though it still has one "
                "demonstrably unfinished workspace effect. The result-file write already completed successfully. "
                f"Do not rewrite {result_path}. The next required effect is a separate client-tool "
                "readback/verification of the existing result file, including the trailing-newline requirement "
                "from the original acceptance request."
            )
            if repeated:
                correction += (
                    " This incomplete acknowledgement has already repeated. Do not repeat the write or return "
                    "another acknowledgement before the independent readback completes."
                )
            action = (
                f"Call {preferred_name} now to perform a separate byte-level readback and verify the existing {result_path}, "
                "including the trailing newline. Return only the corrected tool-call output."
            )
        else:
            correction = (
                "The previous reply stopped the synthetic acceptance request while required workspace effects "
                "remain unfinished. The workspace validation already completed successfully, "
                f"but a successful write of {result_path} has not yet been proven. Continue from that next "
                "unfinished step; do not repeat the successful workspace validation."
            )
            if repeated:
                correction += (
                    " This incomplete acknowledgement has already repeated. Continue the pending effect instead "
                    "of returning another acknowledgement."
                )
            action = (
                f"Call {preferred_name} now to create {result_path} exactly as required by the Original user "
                "request. Return only the corrected tool-call output."
            )
    elif looks_like_premature_acceptance_success(
        assistant_text,
        messages,
    ):
        correction = (
            "The previous reply returned the acceptance success sentinel before the requested workspace effects "
            "were proven. A successful workspace-validation exec_command is only the first step. The acceptance "
            "request still requires creating the specified result file and then performing a separate client-tool "
            "readback/verification before the success sentinel is valid."
        )
        if repeated:
            correction += (
                " This premature success has already repeated. Do not return the success sentinel again until the "
                "remaining write and readback steps have completed successfully."
            )
        action = (
            f"Call {preferred_name} now to execute the next unfinished post-validation workspace step from the "
            "Original user request. Return only the corrected tool-call output."
        )
    elif looks_like_false_acceptance_workspace_mismatch(
        assistant_text,
        messages,
    ):
        correction = (
            "The previous reply incorrectly returned ACCEPTANCE_WORKSPACE_MISMATCH even though the real client "
            "workspace-validation exec_command already completed with exit code 0. The user's contract says that "
            "sentinel is allowed only when the complete validation command exits non-zero. Treat the successful "
            "tool result as authoritative and continue the unfinished post-validation steps."
        )
        if repeated:
            correction += (
                " This false mismatch sentinel has already repeated. Do not rerun or reinterpret the successful "
                "workspace validation as a failure."
            )
        action = (
            f"Call {preferred_name} now to execute the next unfinished workspace step from the current acceptance "
            "request or compacted continuation state. Return only the corrected tool-call output."
        )
    elif (
        compacted_context
        and looks_like_compacted_state_only_acknowledgement(
            assistant_text
        )
    ):
        correction = (
            "The previous reply stopped after acknowledging that the compacted context and durable exact value were restored. "
            "That acknowledgement is not task completion. The ACTIVE CONTINUATION STATE below still contains unresolved "
            "workspace actions that must be executed with the declared client tool."
        )
        if repeated:
            correction += (
                " This premature state-only completion has already repeated. Do not restate the recovered token or context again."
            )
        action = (
            f"Call {preferred_name} now to execute the next unfinished workspace step from the compacted continuation state. "
            "Return only the corrected tool-call output."
        )
    elif (
        compacted_context
        and looks_like_missing_task_clarification(
            assistant_text
        )
    ):
        correction = (
            "The previous reply incorrectly asked the user to resend or restate the task. "
            "The pending task and verification steps are already recorded in the compacted continuation state below. "
            "Treat that ACTIVE CONTINUATION STATE as authoritative and continue from the next unfinished workspace step."
        )
        if repeated:
            correction += (
                " This clarification loop has already repeated. Do not ask for the task, command, or verification steps again."
            )
        action = (
            f"Call {preferred_name} now to execute the next pending workspace step from the compacted continuation state. "
            "Return only the corrected tool-call output."
        )
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

    compacted_block = (
        "Compacted continuation state already present in this conversation:\n"
        + compacted_context
        + "\n\n"
        if compacted_context
        else ""
    )

    user = (
        "[Client Workspace Repair]\n"
        f"Attempt: {attempt}/{total_attempts}\n"
        f"{correction}\n\n"
        + compacted_block
        + "Original user request:\n"
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
    "has_redundant_acceptance_tool_call_after_completion",
    "has_suspicious_root_workdir_tool_call",
    "looks_like_client_access_refusal",
    "looks_like_local_workspace_request",
    "looks_like_missing_task_clarification",
    "looks_like_compacted_state_only_acknowledgement",
    "looks_like_post_tool_unavailable_claim",
    "looks_like_false_acceptance_workspace_mismatch",
    "looks_like_acceptance_completion_without_exact_sentinel",
    "looks_like_incomplete_acceptance_continuation",
    "looks_like_premature_acceptance_success",
    "should_repair_client_workspace_refusal",
    "user_explicitly_requested_root_workdir",
]
