import pytest

from app.services.client_tool_policy import (
    build_client_workspace_repair_messages,
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


def _successful_read_history():
    return [
        {"role": "user", "content": "检查 calc.py，修复 add 函数并运行最小测试。"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_read",
                    "type": "function",
                    "function": {
                        "name": "exec_command",
                        "arguments": '{"cmd":"pwd && cat calc.py"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_read",
            "name": "exec_command",
            "content": "Process exited with code 0\nFinal output:\ndef add(a, b):\n    return a - b\n",
        },
    ]


def test_detects_false_local_workspace_refusal_before_any_tool_result(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = [
        {
            "role": "user",
            "content": "Inspect calc.py, fix add(2, 3), and run a real test in the local workspace.",
        }
    ]
    parsed = {
        "mode": "final",
        "content": "I cannot access your local files. Please upload calc.py.",
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=parsed["content"],
        parsed=parsed,
    ) is True


def test_detects_chatgpt_claim_that_codex_workspace_is_not_mounted(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = [
        {
            "role": "user",
            "content": "检查当前工作区的 calc.py，修复 add 函数，然后实际运行一个最小测试。",
        }
    ]
    refusal = (
        "当前这个会话实际可用的文件系统里没有挂载本机工作区，因此我无法真实读取或修改其中的 "
        "calc.py，也不能声称测试已经运行成功。需要由能够访问该本机工作区的执行工具完成这两步。"
    )
    parsed = {"mode": "final", "content": refusal, "tool_calls": []}

    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=refusal,
        parsed=parsed,
    ) is True


def test_repairs_false_tool_unavailable_claim_after_successful_client_call(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = _successful_read_history()
    refusal = (
        "已确认 calc.py 当前执行的是减法。但当前这个会话实际没有暴露你贴出的 exec_command 本地执行工具，"
        "我无法在工作区上真实写入并运行测试，因此不能声称已经修复。"
    )
    parsed = {"mode": "final", "content": refusal, "tool_calls": []}

    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=refusal,
        parsed=parsed,
    ) is True


def test_does_not_override_a_genuine_failure_after_tool_history(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = [
        {"role": "user", "content": "Inspect calc.py and run its tests."},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "exec_command",
                        "arguments": '{"cmd":"cat calc.py"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "exec_command",
            "content": "cat: calc.py: No such file or directory",
        },
    ]
    parsed = {
        "mode": "final",
        "content": "I cannot read calc.py because the tool confirmed that the file does not exist.",
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=parsed["content"],
        parsed=parsed,
    ) is False


def test_repair_prompt_explains_client_side_execution_without_bypassing_permissions():
    messages = [{"role": "user", "content": "Fix calc.py and test it."}]
    repair = build_client_workspace_repair_messages(
        messages=messages,
        tools=EXEC_TOOLS,
        assistant_text="I cannot access your local files.",
        attempt=1,
        total_attempts=3,
    )

    assert len(repair) == 2
    system = repair[0]["content"]
    assert "exec_command" in system
    assert "client tools DO execute on the user's machine" in system
    assert "sandbox and approval policy" in system
    assert "Browser-visible filesystem state is not authoritative" in system
    assert "Only report a missing path" in system
    assert "Do not invent tool results" in system


def test_post_tool_repair_prompt_states_prior_call_proves_tool_is_exposed():
    repair = build_client_workspace_repair_messages(
        messages=_successful_read_history(),
        tools=EXEC_TOOLS,
        assistant_text="当前会话没有暴露 exec_command。",
        attempt=1,
        total_attempts=3,
    )

    assert "prior workspace client tool call/result" in repair[0]["content"]
    assert "proves the client tool is exposed" in repair[0]["content"]
    assert "Continue the task by calling exec_command again" in repair[1]["content"]


def test_roundtrip_repairs_refusal_into_exec_command(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")
    replies = iter(
        [
            "I cannot access your local files. Please upload calc.py.",
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"cat calc.py","workdir":"."}'
                ']]></arguments></call></adapter_calls>'
            ),
        ]
    )
    seen_messages = []

    def executor(browser_messages):
        seen_messages.append(browser_messages)
        return next(replies)

    result = complete_tool_calling_roundtrip(
        messages=[
            {
                "role": "user",
                "content": "Inspect calc.py, fix the add function, and run a real test.",
            }
        ],
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=executor,
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"
    assert len(seen_messages) == 2
    assert "Client Workspace Repair" in seen_messages[1][1]["content"]


def test_roundtrip_repairs_mounted_workspace_deflection(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")
    replies = iter(
        [
            "当前这个会话实际可用的文件系统里没有挂载工作区，因此我无法真实读取或修改 calc.py。",
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"pwd && ls -la && cat calc.py"}'
                ']]></arguments></call></adapter_calls>'
            ),
        ]
    )

    result = complete_tool_calling_roundtrip(
        messages=[{"role": "user", "content": "检查 calc.py，修复它并运行测试。"}],
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=lambda _messages: next(replies),
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"


def test_roundtrip_repairs_post_tool_unavailable_claim_into_next_exec(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")
    replies = iter(
        [
            "已确认 calc.py 是减法，但当前这个会话实际没有暴露 exec_command 本地执行工具，无法真实写入并测试。",
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"echo PASS"}'
                ']]></arguments></call></adapter_calls>'
            ),
        ]
    )

    result = complete_tool_calling_roundtrip(
        messages=_successful_read_history(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=lambda _messages: next(replies),
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"


def test_roundtrip_fails_closed_after_repeated_false_refusals(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "1")

    def executor(_browser_messages):
        return "I cannot access your local workspace. Please upload the file."

    with pytest.raises(RuntimeError, match="client_workspace_tool_refusal"):
        complete_tool_calling_roundtrip(
            messages=[{"role": "user", "content": "Fix calc.py and run the test."}],
            tools=EXEC_TOOLS,
            tool_choice="auto",
            parallel_tool_calls=False,
            round_executor=executor,
        )
