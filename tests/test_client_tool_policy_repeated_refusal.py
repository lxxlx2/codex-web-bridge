import pytest

from app.services.client_tool_policy import should_repair_client_workspace_refusal
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


def _history_with_real_exec_and_user_shaped_tool_output():
    return [
        {"role": "user", "content": "修复 failure_recovery/parser.py 并运行真实测试。"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_real",
                    "type": "function",
                    "function": {
                        "name": "exec_command",
                        "arguments": '{"cmd":"pwd && cat failure_recovery/parser.py"}',
                    },
                }
            ],
        },
        {
            "role": "user",
            "content": "Process exited with code 0. Final output: parser.py contents returned by the client tool.",
        },
    ]


def test_post_tool_tool_list_absence_claim_is_repaired_even_when_latest_user_is_tool_output(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    refusal = "当前实际可调用工具中没有名为 exec_command 的客户端工具，因此无法继续执行。"
    parsed = {"mode": "final", "content": refusal, "tool_calls": []}

    assert should_repair_client_workspace_refusal(
        messages=_history_with_real_exec_and_user_shaped_tool_output(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=refusal,
        parsed=parsed,
    ) is True


def test_roundtrip_retries_a_repeated_tool_list_absence_claim_until_exec_command(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")
    refusal = "当前实际可调用工具中没有名为 exec_command 的客户端工具，因此无法继续执行。"
    replies = iter(
        [
            refusal,
            refusal,
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"python3 -m unittest discover -s failure_recovery/tests -v"}'
                ']]></arguments></call></adapter_calls>'
            ),
        ]
    )
    seen = []

    def executor(browser_messages):
        seen.append(browser_messages)
        return next(replies)

    result = complete_tool_calling_roundtrip(
        messages=_history_with_real_exec_and_user_shaped_tool_output(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=executor,
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"
    assert len(seen) == 3
    assert "repeated contradiction" in seen[2][1]["content"]


def test_roundtrip_fails_closed_if_exact_tool_list_refusal_never_recovers(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")
    refusal = "当前实际可调用工具中没有名为 exec_command 的客户端工具，因此无法继续执行。"

    with pytest.raises(RuntimeError, match="client_workspace_tool_refusal"):
        complete_tool_calling_roundtrip(
            messages=_history_with_real_exec_and_user_shaped_tool_output(),
            tools=EXEC_TOOLS,
            tool_choice="auto",
            parallel_tool_calls=False,
            round_executor=lambda _messages: refusal,
        )
