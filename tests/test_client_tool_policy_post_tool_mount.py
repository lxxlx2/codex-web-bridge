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
                        "arguments": '{"cmd":"cat calc.py","workdir":"/tmp/project"}',
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


def test_repairs_post_tool_claim_that_execution_environment_is_not_mounted(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = _successful_read_history()
    refusal = (
        "已确认当前 calc.py 的问题在 return a - b。"
        "我也尝试继续访问本地文件来完成修改和测试，但当前这轮实际可调用的执行环境没有挂载该本地工作区，"
        "因此无法真实写入文件，也不能声称测试已经通过。"
    )
    parsed = {"mode": "final", "content": refusal, "tool_calls": []}

    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=refusal,
        parsed=parsed,
    ) is True


def test_roundtrip_repairs_post_tool_mount_claim_into_next_exec(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")
    replies = iter(
        [
            "当前这轮实际可调用的执行环境没有挂载该本地工作区，因此无法真实写入文件。",
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"cat calc.py","workdir":"/tmp/project"}'
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
