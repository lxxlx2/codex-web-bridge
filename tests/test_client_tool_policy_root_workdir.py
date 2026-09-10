import json

import pytest

from app.services.client_tool_policy import (
    has_suspicious_root_workdir_tool_call,
    should_repair_client_workspace_refusal,
)
from app.services.tool_calling import complete_tool_calling_roundtrip


EXEC_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "exec_command",
            "description": "Run a shell command in the local client workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string"},
                    "workdir": {"type": "string"},
                },
                "required": ["cmd"],
                "additionalProperties": False,
            },
        },
    }
]


def _tool_call(arguments):
    return {
        "id": "call_pwd",
        "type": "function",
        "function": {
            "name": "exec_command",
            "arguments": json.dumps(arguments, ensure_ascii=False),
        },
    }


def test_root_workdir_is_suspicious_when_user_only_requests_current_pwd(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = [{"role": "user", "content": "必须使用 exec_command 执行 pwd，只返回真实输出。"}]
    parsed = {"mode": "tool_calls", "content": None, "tool_calls": [_tool_call({"cmd": "pwd", "workdir": "/"})]}

    assert has_suspicious_root_workdir_tool_call(messages, parsed) is True
    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=(
            '<adapter_calls><call name="exec_command"><arguments encoding="json"><![CDATA['
            '{"cmd":"pwd","workdir":"/"}'
            ']]></arguments></call></adapter_calls>'
        ),
        parsed=parsed,
    ) is True


def test_explicit_root_workdir_request_is_allowed(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = [{"role": "user", "content": "Use exec_command with workdir=/ and run pwd from the filesystem root."}]
    parsed = {"mode": "tool_calls", "content": None, "tool_calls": [_tool_call({"cmd": "pwd", "workdir": "/"})]}

    assert has_suspicious_root_workdir_tool_call(messages, parsed) is False
    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text="tool call",
        parsed=parsed,
    ) is False


def test_direct_declared_exec_command_unavailable_refusal_is_repaired(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = [{"role": "user", "content": "必须使用 exec_command 执行 pwd，只返回真实输出。"}]
    refusal = "exec_command 不可用，无法返回该命令的真实输出。"
    parsed = {"mode": "final", "content": refusal, "tool_calls": []}

    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=refusal,
        parsed=parsed,
    ) is True


def test_roundtrip_repairs_accidental_root_workdir_by_omitting_workdir(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")
    replies = iter(
        [
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"pwd","workdir":"/"}'
                ']]></arguments></call></adapter_calls>'
            ),
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"pwd"}'
                ']]></arguments></call></adapter_calls>'
            ),
        ]
    )
    seen = []

    def executor(browser_messages):
        seen.append(browser_messages)
        return next(replies)

    result = complete_tool_calling_roundtrip(
        messages=[{"role": "user", "content": "必须使用 exec_command 执行 pwd，只返回真实输出。"}],
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=executor,
    )

    assert result["mode"] == "tool_calls"
    args = json.loads(result["tool_calls"][0]["function"]["arguments"])
    assert args == {"cmd": "pwd"}
    assert len(seen) == 2


def test_roundtrip_recovers_when_root_workdir_repair_is_followed_by_tool_unavailable_refusal(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")
    replies = iter(
        [
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"pwd","workdir":"/"}'
                ']]></arguments></call></adapter_calls>'
            ),
            "exec_command 不可用，无法返回该命令的真实输出。",
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"pwd"}'
                ']]></arguments></call></adapter_calls>'
            ),
        ]
    )
    seen = []

    def executor(browser_messages):
        seen.append(browser_messages)
        return next(replies)

    result = complete_tool_calling_roundtrip(
        messages=[{"role": "user", "content": "必须使用 exec_command 执行 pwd，只返回真实输出。"}],
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=executor,
    )

    assert result["mode"] == "tool_calls"
    args = json.loads(result["tool_calls"][0]["function"]["arguments"])
    assert args == {"cmd": "pwd"}
    assert len(seen) == 3


def test_roundtrip_fails_closed_if_model_keeps_forcing_root_workdir(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "1")
    bad = (
        '<adapter_calls><call name="exec_command">'
        '<arguments encoding="json"><![CDATA['
        '{"cmd":"pwd","workdir":"/"}'
        ']]></arguments></call></adapter_calls>'
    )

    with pytest.raises(RuntimeError, match="client_workspace_tool_refusal"):
        complete_tool_calling_roundtrip(
            messages=[{"role": "user", "content": "必须使用 exec_command 执行 pwd，只返回真实输出。"}],
            tools=EXEC_TOOLS,
            tool_choice="auto",
            parallel_tool_calls=False,
            round_executor=lambda _messages: bad,
        )
