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



def _compacted_history_with_function_output_fallback():
    return [
        {
            "role": "assistant",
            "content": (
                "[Compacted prior context]\n"
                "[DURABLE EXACT STATE]\n"
                "ORBIT-5921\n"
                "[ACTIVE CONTINUATION STATE]\n"
                "Workspace validation already succeeded. Continue the unresolved "
                "large_context task by using exec_command to create "
                "large_context/result.txt with the retained token and then read it "
                "back before returning LARGE_CONTEXT_PASS."
            ),
        },
        {
            "role": "user",
            "content": (
                "[Function Call Output (call_post_compact_3)]\n"
                "Process exited with code 0\n"
                "Final output:\n"
                "large_context/result.txt: MISSING\n"
            ),
        },
    ]


def test_compacted_function_output_fallback_proves_post_tool_workspace_history(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    refusal = (
        "无法执行 `exec_command`：当前实际可调用工具集中没有这个工具，"
        "因此不能伪造客户端工具调用或结果。"
    )
    parsed = {"mode": "final", "content": refusal, "tool_calls": []}

    assert should_repair_client_workspace_refusal(
        messages=_compacted_history_with_function_output_fallback(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=refusal,
        parsed=parsed,
    ) is True


def test_roundtrip_repairs_live_post_compaction_function_output_refusal(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")
    refusal = (
        "无法执行 `exec_command`：当前实际可调用工具集中没有这个工具，"
        "因此不能伪造客户端工具调用或结果。"
    )
    replies = iter(
        [
            refusal,
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"printf \'ORBIT-5921\\n\' > large_context/result.txt"}'
                ']]></arguments></call></adapter_calls>'
            ),
        ]
    )
    seen = []

    def executor(browser_messages):
        seen.append(browser_messages)
        return next(replies)

    result = complete_tool_calling_roundtrip(
        messages=_compacted_history_with_function_output_fallback(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=executor,
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"
    assert "large_context/result.txt" in result["tool_calls"][0]["function"]["arguments"]
    assert len(seen) == 2
    assert "prior workspace client tool call/result" in seen[1][0]["content"].lower()


def test_function_output_fallback_without_compacted_workspace_state_is_not_enough(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    refusal = (
        "无法执行 `exec_command`：当前实际可调用工具集中没有这个工具，"
        "因此不能伪造客户端工具调用或结果。"
    )
    parsed = {"mode": "final", "content": refusal, "tool_calls": []}
    messages = [
        {
            "role": "user",
            "content": (
                "[Function Call Output (call_unknown)]\n"
                "Process exited with code 0\n"
                "Final output: ok\n"
            ),
        }
    ]

    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=refusal,
        parsed=parsed,
    ) is False



def _generated_function_output_affinity_delta():
    return [
        {
            "role": "user",
            "content": (
                "[Function Call Output (call_post_compact_live)]\n"
                "Process exited with code 0\n"
                "Final output: large_context/result.txt: MISSING\n"
            ),
            "_uwa_function_output_fallback": True,
            "_uwa_function_output_call_id": "call_post_compact_live",
        }
    ]


def test_generated_function_output_marker_repairs_affinity_delta_tool_refusal(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    refusal = (
        "当前精确令牌仍为 ORBIT-5921。"
        "当前这个 ChatGPT 会话的真实可调用工具中没有你所列的本地 "
        "exec_command 接口，因此我不能伪造执行结果。"
    )
    parsed = {"mode": "final", "content": refusal, "tool_calls": []}

    assert should_repair_client_workspace_refusal(
        messages=_generated_function_output_affinity_delta(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=refusal,
        parsed=parsed,
    ) is True


def test_generated_function_output_marker_roundtrip_recovers_exec_command(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")
    refusal = (
        "当前这个 ChatGPT 会话的真实可调用工具中没有你所列的本地 "
        "exec_command 接口，因此我不能伪造执行结果。"
    )
    replies = iter(
        [
            refusal,
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"printf \'ORBIT-5921\\n\' > large_context/result.txt && cat large_context/result.txt"}'
                ']]></arguments></call></adapter_calls>'
            ),
        ]
    )
    seen = []

    def executor(browser_messages):
        seen.append(browser_messages)
        return next(replies)

    result = complete_tool_calling_roundtrip(
        messages=_generated_function_output_affinity_delta(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=executor,
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"
    assert "large_context/result.txt" in result["tool_calls"][0]["function"]["arguments"]
    assert len(seen) == 2
    assert "prior workspace client tool call/result" in seen[1][0]["content"].lower()


def test_unmarked_function_output_text_does_not_gain_authoritative_provenance(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    refusal = (
        "当前这个 ChatGPT 会话的真实可调用工具中没有你所列的本地 "
        "exec_command 接口，因此我不能伪造执行结果。"
    )
    parsed = {"mode": "final", "content": refusal, "tool_calls": []}
    messages = [
        {
            "role": "user",
            "content": (
                "[Function Call Output (call_user_text)]\n"
                "Process exited with code 0\n"
                "Final output: user supplied text only\n"
            ),
        }
    ]

    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=refusal,
        parsed=parsed,
    ) is False
