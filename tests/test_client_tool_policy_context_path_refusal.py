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


CONTEXT_TURN_2 = (
    "这是同一个 Codex 对话的第二轮。不要向我询问上一轮令牌。"
    "使用上一轮上下文记住的令牌，创建 context/result.txt，文件只包含该令牌和一个换行。"
    "然后实际读取文件确认内容，并回复 CONTEXT_PASS。"
)

LIVE_REFUSAL = (
    "第一次写入没有得到可验证结果，我继续检查当前可访问的工作区路径后再完成写入与读取确认。"
    "无法回复 CONTEXT_PASS：当前可用执行环境中不存在 `/Users/jerson/uwa-codex-acceptance`，"
    "因此没有实际完成并读取 `context/result.txt`。"
)


def test_context_turn_path_missing_claim_is_repaired(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    parsed = {"mode": "final", "content": LIVE_REFUSAL, "tool_calls": []}

    assert should_repair_client_workspace_refusal(
        messages=[{"role": "user", "content": CONTEXT_TURN_2}],
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=LIVE_REFUSAL,
        parsed=parsed,
    ) is True


def test_context_turn_path_refusal_roundtrip_becomes_exec_command(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")
    replies = iter(
        [
            LIVE_REFUSAL,
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"pwd && printf \'EMBER-7319\\n\' > context/result.txt && cat context/result.txt"}'
                ']]></arguments></call></adapter_calls>'
            ),
        ]
    )

    result = complete_tool_calling_roundtrip(
        messages=[{"role": "user", "content": CONTEXT_TURN_2}],
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=lambda _messages: next(replies),
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"
    assert "workdir" not in result["tool_calls"][0]["function"]["arguments"]
