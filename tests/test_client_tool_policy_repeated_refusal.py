import pytest

from app.services.client_tool_policy import (
    has_redundant_acceptance_tool_call_after_completion,
    looks_like_acceptance_completion_without_exact_sentinel,
    looks_like_incomplete_acceptance_continuation,
    looks_like_premature_acceptance_success,
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



def _restart_context_history_after_validation():
    request = (
        "这是同一个 Codex 对话的第二轮重启恢复验收。"
        "第一步必须通过客户端 exec_command 在当前工作区执行 "
        "pwd && test -f .uwa_codex_acceptance && test -d context。"
        "校验成功后，只使用上一轮对话上下文中记住的令牌，并且必须通过客户端 exec_command "
        "创建 context/result.txt，使文件精确包含该令牌和一个换行；随后再次通过客户端 exec_command "
        "读取并确认该文件。完成后只回复 CONTEXT_PASS。"
    )
    return [
        {"role": "user", "content": request},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_validate",
                    "type": "function",
                    "function": {
                        "name": "exec_command",
                        "arguments": (
                            '{"cmd":"pwd && test -f .uwa_codex_acceptance '
                            '&& test -d context"}'
                        ),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_validate",
            "name": "exec_command",
            "content": "Process exited with code 0\nFinal output:\n/acceptance\n",
        },
    ]


def _append_successful_exec(messages, call_id, command, output="ok"):
    messages.extend(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": "exec_command",
                            "arguments": '{"cmd":' + __import__("json").dumps(command) + "}",
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": call_id,
                "name": "exec_command",
                "content": (
                    "Process exited with code 0\n"
                    f"Final output:\n{output}\n"
                ),
            },
        ]
    )


def test_live_context_pass_after_only_validation_is_repaired(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = _restart_context_history_after_validation()
    parsed = {
        "mode": "final",
        "content": "CONTEXT_PASS",
        "tool_calls": [],
    }

    assert looks_like_premature_acceptance_success(
        "CONTEXT_PASS",
        messages,
    ) is True

    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text="CONTEXT_PASS",
        parsed=parsed,
    ) is True


def test_roundtrip_repairs_live_context_pass_into_next_exec(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")

    replies = iter(
        [
            "CONTEXT_PASS",
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"printf \'%s\\n\' \'EMBER-7319\' > context/result.txt"}'
                ']]></arguments></call></adapter_calls>'
            ),
        ]
    )
    seen = []

    def executor(browser_messages):
        seen.append(browser_messages)
        return next(replies)

    result = complete_tool_calling_roundtrip(
        messages=_restart_context_history_after_validation(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=executor,
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"
    assert "context/result.txt" in result["tool_calls"][0]["function"]["arguments"]
    assert len(seen) == 2
    assert "success sentinel before" in seen[1][1]["content"]


def test_context_pass_allowed_after_successful_write_and_separate_readback(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = _restart_context_history_after_validation()
    _append_successful_exec(
        messages,
        "call_write",
        "printf '%s\\n' 'EMBER-7319' > context/result.txt",
    )
    _append_successful_exec(
        messages,
        "call_read",
        "cat context/result.txt && tail -c 1 context/result.txt | od -An -t x1",
        "EMBER-7319",
    )

    parsed = {
        "mode": "final",
        "content": "CONTEXT_PASS",
        "tool_calls": [],
    }

    assert looks_like_premature_acceptance_success(
        "CONTEXT_PASS",
        messages,
    ) is False
    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text="CONTEXT_PASS",
        parsed=parsed,
    ) is False



def test_acceptance_incomplete_after_write_requires_readback_repair(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = _restart_context_history_after_validation()
    _append_successful_exec(
        messages,
        "call_write",
        "printf '%s\\n' 'EMBER-7319' > context/result.txt",
    )
    parsed = {
        "mode": "final",
        "content": "ACCEPTANCE_INCOMPLETE",
        "tool_calls": [],
    }

    assert looks_like_incomplete_acceptance_continuation(
        "ACCEPTANCE_INCOMPLETE",
        messages,
    ) is True
    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text="ACCEPTANCE_INCOMPLETE",
        parsed=parsed,
    ) is True


def test_roundtrip_repairs_acceptance_incomplete_to_separate_readback(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")
    messages = _restart_context_history_after_validation()
    _append_successful_exec(
        messages,
        "call_write",
        "printf '%s\\n' 'EMBER-7319' > context/result.txt",
    )
    replies = iter(
        [
            "ACCEPTANCE_INCOMPLETE",
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"cat context/result.txt && tail -c 1 context/result.txt | od -An -t x1"}'
                ']]></arguments></call></adapter_calls>'
            ),
        ]
    )
    seen = []

    def executor(browser_messages):
        seen.append(browser_messages)
        return next(replies)

    result = complete_tool_calling_roundtrip(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=executor,
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"
    arguments = result["tool_calls"][0]["function"]["arguments"]
    assert "context/result.txt" in arguments
    assert "cat context/result.txt && tail -c 1 context/result.txt | od -An -t x1" in arguments
    assert "od -An -t x1" in arguments
    assert len(seen) == 2
    assert "Do not rewrite context/result.txt" in seen[1][1]["content"]
    assert "separate client-tool readback" in seen[1][1]["content"]


def test_live_step_execution_stall_after_validation_continues_to_write(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")
    messages = _restart_context_history_after_validation()
    refusal = "第二步未能通过客户端 `exec_command` 执行，因此不能回复 `CONTEXT_PASS`。"
    parsed = {
        "mode": "final",
        "content": refusal,
        "tool_calls": [],
    }

    assert looks_like_incomplete_acceptance_continuation(
        refusal,
        messages,
    ) is True
    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=refusal,
        parsed=parsed,
    ) is True


def test_roundtrip_repairs_live_step_execution_stall_into_write(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")
    messages = _restart_context_history_after_validation()
    refusal = "第二步未能通过客户端 `exec_command` 执行，因此不能回复 `CONTEXT_PASS`。"
    replies = iter(
        [
            refusal,
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"printf \'%s\\\\n\' \'EMBER-7319\' > context/result.txt"}'
                ']]></arguments></call></adapter_calls>'
            ),
        ]
    )
    seen = []

    def executor(browser_messages):
        seen.append(browser_messages)
        return next(replies)

    result = complete_tool_calling_roundtrip(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=executor,
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"
    assert "context/result.txt" in result["tool_calls"][0]["function"]["arguments"]
    assert len(seen) == 2
    assert "workspace validation already completed successfully" in seen[1][1]["content"].lower()
    assert "successful write of context/result.txt has not yet been proven" in seen[1][1]["content"]


def test_step_execution_stall_without_synthetic_contract_is_not_repaired(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    refusal = "第二步未能通过客户端 `exec_command` 执行，因此不能回复 `CONTEXT_PASS`。"
    messages = [
        {
            "role": "user",
            "content": "Discuss this sentence as text only; do not access a workspace.",
        }
    ]
    parsed = {
        "mode": "final",
        "content": refusal,
        "tool_calls": [],
    }

    assert looks_like_incomplete_acceptance_continuation(
        refusal,
        messages,
    ) is False
    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=refusal,
        parsed=parsed,
    ) is False


def test_live_third_step_validation_stall_after_write_continues_to_byte_readback(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = _restart_context_history_after_validation()
    _append_successful_exec(
        messages,
        "call_write",
        "printf '%s\\n' 'EMBER-7319' > context/result.txt",
    )
    refusal = "第三步无法在当前执行环境完成验证，因此不能回复 CONTEXT_PASS。"
    parsed = {
        "mode": "final",
        "content": refusal,
        "tool_calls": [],
    }

    assert looks_like_incomplete_acceptance_continuation(
        refusal,
        messages,
    ) is True
    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=refusal,
        parsed=parsed,
    ) is True


def test_roundtrip_repairs_live_third_step_stall_without_rewriting_result(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")
    messages = _restart_context_history_after_validation()
    _append_successful_exec(
        messages,
        "call_write",
        "printf '%s\\n' 'EMBER-7319' > context/result.txt",
    )
    refusal = "第三步无法在当前执行环境完成验证，因此不能回复 CONTEXT_PASS。"
    replies = iter(
        [
            refusal,
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"cat context/result.txt && tail -c 1 context/result.txt | od -An -t x1"}'
                ']]></arguments></call></adapter_calls>'
            ),
        ]
    )
    seen = []

    def executor(browser_messages):
        seen.append(browser_messages)
        return next(replies)

    result = complete_tool_calling_roundtrip(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=executor,
    )

    assert result["mode"] == "tool_calls"
    arguments = result["tool_calls"][0]["function"]["arguments"]
    assert "context/result.txt" in arguments
    assert "od -An -t x1" in arguments
    assert "printf '%s\\n' 'EMBER-7319' > context/result.txt" not in arguments
    assert len(seen) == 2
    assert "Do not rewrite context/result.txt" in seen[1][1]["content"]
    assert "separate client-tool readback" in seen[1][1]["content"]


def test_live_third_step_stall_after_completed_effects_is_not_unfinished(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = _restart_context_history_after_validation()
    _append_successful_exec(
        messages,
        "call_write",
        "printf '%s\\n' 'EMBER-7319' > context/result.txt",
    )
    _append_successful_exec(
        messages,
        "call_read",
        "cat context/result.txt && tail -c 1 context/result.txt | od -An -t x1",
        "EMBER-7319",
    )
    refusal = "第三步无法在当前执行环境完成验证，因此不能回复 CONTEXT_PASS。"

    assert looks_like_incomplete_acceptance_continuation(
        refusal,
        messages,
    ) is False


def test_premature_pass_requires_readback_after_last_write(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = _restart_context_history_after_validation()
    _append_successful_exec(
        messages,
        "call_write_1",
        "printf '%s\\n' 'EMBER-7319' > context/result.txt",
    )
    _append_successful_exec(
        messages,
        "call_read_1",
        "od -An -t x1 context/result.txt",
        "45 4d 42 45 52 2d 37 33 31 39 0a",
    )
    _append_successful_exec(
        messages,
        "call_write_2",
        "printf '%s\\n' 'EMBER-7319' > context/result.txt",
    )

    assert looks_like_premature_acceptance_success(
        "CONTEXT_PASS",
        messages,
    ) is True


def test_step_execution_stall_after_completed_effects_is_not_unfinished(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = _restart_context_history_after_validation()
    _append_successful_exec(
        messages,
        "call_write",
        "printf '%s\\n' 'EMBER-7319' > context/result.txt",
    )
    _append_successful_exec(
        messages,
        "call_read",
        "cat context/result.txt && tail -c 1 context/result.txt | od -An -t x1",
        "EMBER-7319",
    )
    refusal = "第三步未能通过客户端 `exec_command` 执行，因此不能回复 `CONTEXT_PASS`。"

    assert looks_like_incomplete_acceptance_continuation(
        refusal,
        messages,
    ) is False


def test_large_context_step_execution_stall_uses_shared_acceptance_policy(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = _large_context_history_after_validation()
    refusal = "第二步未能通过客户端 `exec_command` 执行，因此不能回复 `LARGE_CONTEXT_PASS`。"

    assert looks_like_incomplete_acceptance_continuation(
        refusal,
        messages,
    ) is True


def test_live_acceptance_capability_refusal_after_read_only_checks_continues_to_write(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = _large_context_history_after_validation()
    _append_successful_exec(
        messages,
        "call_list_root",
        "pwd && printf '\\n--- listing ---\\n' && ls -la",
    )
    _append_successful_exec(
        messages,
        "call_list_large",
        "pwd && ls -la && ls -la large_context",
    )
    _append_successful_exec(
        messages,
        "call_missing_probe",
        (
            "pwd && if [ -f large_context/result.txt ]; then "
            "wc -c < large_context/result.txt; "
            "od -An -tx1 -v large_context/result.txt; "
            "cat large_context/result.txt; "
            "else printf 'MISSING\\n'; fi"
        ),
        "MISSING",
    )
    refusal = (
        "当前运行环境无法访问 `/Users/jerson/uwa-codex-acceptance`，"
        "并且没有实际可调用的 `exec_command` 客户端工具，因此无法真实写入并完成字节级校验。"
        "只有真实工具完成写入并再次验证后，才能返回 `LARGE_CONTEXT_PASS`。"
        "因此当前不能声称通过，也不能输出该成功标记。"
    )
    parsed = {
        "mode": "final",
        "content": refusal,
        "tool_calls": [],
    }

    assert looks_like_incomplete_acceptance_continuation(
        refusal,
        messages,
    ) is True
    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=refusal,
        parsed=parsed,
    ) is True


def test_roundtrip_repairs_live_acceptance_capability_refusal_into_missing_write(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")
    messages = _large_context_history_after_validation()
    _append_successful_exec(
        messages,
        "call_missing_probe",
        (
            "if [ -f large_context/result.txt ]; then "
            "od -An -tx1 -v large_context/result.txt; "
            "cat large_context/result.txt; "
            "else printf 'MISSING\\n'; fi"
        ),
        "MISSING",
    )
    refusal = (
        "当前运行环境无法访问 `/Users/jerson/uwa-codex-acceptance`，"
        "并且没有实际可调用的 `exec_command` 客户端工具，因此无法真实写入并完成字节级校验。"
        "只有真实工具完成写入并再次验证后，才能返回 `LARGE_CONTEXT_PASS`。"
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
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=executor,
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"
    assert "large_context/result.txt" in result["tool_calls"][0]["function"]["arguments"]
    assert len(seen) == 2
    assert "successful write of large_context/result.txt has not yet been proven" in seen[1][1]["content"]


def test_acceptance_capability_refusal_without_successful_validation_is_not_repaired(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = [
        {
            "role": "user",
            "content": (
                "Create large_context/result.txt and return LARGE_CONTEXT_PASS, "
                "but do not actually run any tools."
            ),
        }
    ]
    refusal = (
        "当前运行环境无法访问工作区，并且没有实际可调用的 exec_command 客户端工具，"
        "因此不能返回 LARGE_CONTEXT_PASS。"
    )
    parsed = {
        "mode": "final",
        "content": refusal,
        "tool_calls": [],
    }

    assert looks_like_incomplete_acceptance_continuation(
        refusal,
        messages,
    ) is False


def test_acceptance_capability_refusal_after_write_and_later_readback_is_not_unfinished(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = _large_context_history_after_validation()
    _append_successful_exec(
        messages,
        "call_large_write",
        "printf '%s\\n' 'ORBIT-5921' > large_context/result.txt",
    )
    _append_successful_exec(
        messages,
        "call_large_read",
        "cat large_context/result.txt && od -An -tx1 -v large_context/result.txt",
        "ORBIT-5921",
    )
    refusal = (
        "当前运行环境无法访问工作区，并且没有实际可调用的 exec_command 客户端工具，"
        "因此不能返回 LARGE_CONTEXT_PASS。"
    )

    assert looks_like_incomplete_acceptance_continuation(
        refusal,
        messages,
    ) is False


def test_acceptance_incomplete_after_validation_continues_to_write(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")
    messages = _restart_context_history_after_validation()
    replies = iter(
        [
            "ACCEPTANCE_INCOMPLETE",
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"printf \'%s\\\\n\' \'EMBER-7319\' > context/result.txt"}'
                ']]></arguments></call></adapter_calls>'
            ),
        ]
    )
    seen = []

    def executor(browser_messages):
        seen.append(browser_messages)
        return next(replies)

    result = complete_tool_calling_roundtrip(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=executor,
    )

    assert looks_like_incomplete_acceptance_continuation(
        "ACCEPTANCE_INCOMPLETE",
        messages,
    ) is True
    assert result["mode"] == "tool_calls"
    assert "context/result.txt" in result["tool_calls"][0]["function"]["arguments"]
    assert len(seen) == 2
    assert "successful write of context/result.txt has not yet been proven" in seen[1][1]["content"]
    assert "do not repeat the successful workspace validation" in seen[1][1]["content"].lower()


def test_acceptance_incomplete_after_write_and_readback_is_not_unfinished(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = _restart_context_history_after_validation()
    _append_successful_exec(
        messages,
        "call_write",
        "printf '%s\\n' 'EMBER-7319' > context/result.txt",
    )
    _append_successful_exec(
        messages,
        "call_read",
        "cat context/result.txt && tail -c 1 context/result.txt | od -An -t x1",
        "EMBER-7319",
    )
    parsed = {
        "mode": "final",
        "content": "ACCEPTANCE_INCOMPLETE",
        "tool_calls": [],
    }

    assert looks_like_incomplete_acceptance_continuation(
        "ACCEPTANCE_INCOMPLETE",
        messages,
    ) is False
    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text="ACCEPTANCE_INCOMPLETE",
        parsed=parsed,
    ) is False


def test_unrelated_acceptance_incomplete_text_is_not_repaired(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = [
        {
            "role": "user",
            "content": "Return the literal text ACCEPTANCE_INCOMPLETE as an example.",
        }
    ]
    parsed = {
        "mode": "final",
        "content": "ACCEPTANCE_INCOMPLETE",
        "tool_calls": [],
    }

    assert looks_like_incomplete_acceptance_continuation(
        "ACCEPTANCE_INCOMPLETE",
        messages,
    ) is False
    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text="ACCEPTANCE_INCOMPLETE",
        parsed=parsed,
    ) is False


def test_acceptance_incomplete_respects_tool_choice_none(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = _restart_context_history_after_validation()
    _append_successful_exec(
        messages,
        "call_write",
        "printf '%s\\n' 'EMBER-7319' > context/result.txt",
    )
    parsed = {
        "mode": "final",
        "content": "ACCEPTANCE_INCOMPLETE",
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="none",
        assistant_text="ACCEPTANCE_INCOMPLETE",
        parsed=parsed,
    ) is False


def _large_context_history_after_validation():
    request = (
        "Continue the synthetic large-context acceptance task. "
        "First run pwd && test -f .uwa_codex_acceptance && test -d large_context. "
        "Then create large_context/result.txt with the retained token and a trailing newline, "
        "perform a separate client exec_command readback, and only then reply LARGE_CONTEXT_PASS."
    )
    return [
        {"role": "user", "content": request},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_large_validate",
                    "type": "function",
                    "function": {
                        "name": "exec_command",
                        "arguments": (
                            '{"cmd":"pwd && test -f .uwa_codex_acceptance '
                            '&& test -d large_context"}'
                        ),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_large_validate",
            "name": "exec_command",
            "content": "Process exited with code 0\nFinal output:\n/acceptance\n",
        },
    ]


def test_large_context_acceptance_incomplete_uses_shared_unfinished_effect_policy(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = _large_context_history_after_validation()
    _append_successful_exec(
        messages,
        "call_large_write",
        "printf '%s\\n' 'ORBIT-5921' > large_context/result.txt",
    )
    parsed = {
        "mode": "final",
        "content": "ACCEPTANCE_INCOMPLETE",
        "tool_calls": [],
    }

    assert looks_like_incomplete_acceptance_continuation(
        "ACCEPTANCE_INCOMPLETE",
        messages,
    ) is True
    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text="ACCEPTANCE_INCOMPLETE",
        parsed=parsed,
    ) is True


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


def test_declared_tool_absence_repairs_even_without_compacted_workspace_state(monkeypatch):
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
    ) is True



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
    assert "_uwa_function_output_fallback" not in str(seen[0])
    assert "prior workspace client tool call/result" in seen[1][0]["content"].lower()




def _generated_affinity_delta_with_compacted_context():
    compacted = (
        "[Compacted prior context]\n"
        "[DURABLE EXACT STATE]\n"
        "ORBIT-5921\n"
        "[ACTIVE CONTINUATION STATE]\n"
        "Workspace validation is complete. Use exec_command to write "
        "large_context/result.txt with ORBIT-5921, read it back, then return "
        "LARGE_CONTEXT_PASS."
    )
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
            "_uwa_compacted_continuation_context": compacted,
        }
    ]


def test_live_missing_task_clarification_is_repaired_from_private_compacted_context(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    clarification = (
        "当前已确认 exec_command、write_stdin 等本地客户端工具可用。"
        "请直接给出要在当前 workspace 中执行的具体任务，"
        "我会以实际工具结果为准继续操作。"
    )
    parsed = {
        "mode": "final",
        "content": clarification,
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=_generated_affinity_delta_with_compacted_context(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=clarification,
        parsed=parsed,
    ) is True


def test_roundtrip_repairs_live_missing_task_clarification_into_exec(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")
    clarification = (
        "当前已确认 exec_command、write_stdin 等本地客户端工具可用。"
        "请直接给出要在当前 workspace 中执行的具体任务，"
        "我会以实际工具结果为准继续操作。"
    )
    replies = iter(
        [
            clarification,
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
        messages=_generated_affinity_delta_with_compacted_context(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=executor,
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"
    assert "large_context/result.txt" in result["tool_calls"][0]["function"]["arguments"]
    assert len(seen) == 2
    assert "_uwa_compacted_continuation_context" not in str(seen[0])
    assert "ORBIT-5921" in seen[1][1]["content"]
    assert "large_context/result.txt" in seen[1][1]["content"]
    assert "Do not ask for the task" not in seen[1][1]["content"]

def test_live_no_new_acceptance_instruction_ack_is_repaired(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    acknowledgement = (
        "已续接当前状态，并保留精确值 `ORBIT-5921`。\n\n"
        "当前消息里没有新的验收命令、目标文件或预期输出，"
        "因此没有可执行的下一步。直接发下一条验收指令即可。"
    )
    parsed = {
        "mode": "final",
        "content": acknowledgement,
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=_generated_affinity_delta_with_compacted_context(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=acknowledgement,
        parsed=parsed,
    ) is True


def test_roundtrip_repairs_live_no_new_acceptance_instruction_into_exec(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")

    acknowledgement = (
        "已续接当前状态，并保留精确值 `ORBIT-5921`。\n\n"
        "当前消息里没有新的验收命令、目标文件或预期输出，"
        "因此没有可执行的下一步。直接发下一条验收指令即可。"
    )
    replies = iter(
        [
            acknowledgement,
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
        messages=_generated_affinity_delta_with_compacted_context(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=executor,
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"
    assert "large_context/result.txt" in result["tool_calls"][0]["function"]["arguments"]
    assert len(seen) == 2
    assert "ACTIVE CONTINUATION STATE" in seen[1][1]["content"]
    assert "large_context/result.txt" in seen[1][1]["content"]


def test_state_only_resume_ack_without_compacted_workspace_state_is_not_repaired(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    acknowledgement = "已续接当前状态，并保留精确值 `ORBIT-5921`。"
    parsed = {
        "mode": "final",
        "content": acknowledgement,
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=[{"role": "user", "content": "Acknowledge state only."}],
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=acknowledgement,
        parsed=parsed,
    ) is False


def test_live_no_new_task_ack_is_repaired_from_private_compacted_context(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    acknowledgement = (
        "已接收当前上下文。可继续使用的精确测试值为 `ORBIT-5921`。"
        "当前消息没有包含新的具体执行任务。"
    )
    parsed = {
        "mode": "final",
        "content": acknowledgement,
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=_generated_affinity_delta_with_compacted_context(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=acknowledgement,
        parsed=parsed,
    ) is True


def test_roundtrip_repairs_live_no_new_task_ack_into_exec(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")

    acknowledgement = (
        "已接收当前上下文。可继续使用的精确测试值为 `ORBIT-5921`。"
        "当前消息没有包含新的具体执行任务。"
    )
    replies = iter(
        [
            acknowledgement,
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
        messages=_generated_affinity_delta_with_compacted_context(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=executor,
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"
    assert "large_context/result.txt" in result["tool_calls"][0]["function"]["arguments"]
    assert len(seen) == 2
    assert "_uwa_compacted_continuation_context" not in str(seen[0])
    assert "ORBIT-5921" in seen[1][1]["content"]
    assert "large_context/result.txt" in seen[1][1]["content"]


def test_declared_workspace_tool_absence_claim_is_repaired_without_surviving_history(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")

    refusal = (
        "当前运行环境没有暴露 `exec_command` 或 `write_stdin`，"
        "因此这一轮无法真实写入并验证 "
        "`/Users/jerson/uwa-codex-acceptance/large_context/result.txt`。"
    )
    parsed = {
        "mode": "final",
        "content": refusal,
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=[
            {
                "role": "user",
                "content": "continue",
            }
        ],
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=refusal,
        parsed=parsed,
    ) is True


def test_roundtrip_repairs_declared_tool_absence_after_compaction_history_loss(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")

    refusal = (
        "当前运行环境没有暴露 `exec_command` 或 `write_stdin`，"
        "因此这一轮无法真实写入并验证结果文件。"
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
        messages=[
            {
                "role": "user",
                "content": "continue",
            }
        ],
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=executor,
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"
    assert "large_context/result.txt" in result["tool_calls"][0]["function"]["arguments"]
    assert len(seen) == 2


def test_declared_tool_absence_claim_is_not_repaired_when_tool_choice_none(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")

    refusal = (
        "当前运行环境没有暴露 `exec_command`，因此无法继续。"
    )

    parsed = {
        "mode": "final",
        "content": refusal,
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=[{"role": "user", "content": "continue"}],
        tools=EXEC_TOOLS,
        tool_choice="none",
        assistant_text=refusal,
        parsed=parsed,
    ) is False


def test_unmarked_function_output_text_does_not_gain_authoritative_provenance(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    parsed = {
        "mode": "final",
        "content": "Task state noted.",
        "tool_calls": [],
    }
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
        assistant_text="Task state noted.",
        parsed=parsed,
    ) is False


def test_unmarked_function_output_cannot_hide_declared_tool_absence_contradiction(monkeypatch):
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
    ) is True

def test_plain_cat_after_write_does_not_satisfy_byte_level_acceptance_readback(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = _restart_context_history_after_validation()
    _append_successful_exec(
        messages,
        "call_write",
        "printf '%s\\n' 'EMBER-7319' > context/result.txt",
    )
    _append_successful_exec(
        messages,
        "call_cat",
        "cat context/result.txt",
        "EMBER-7319",
    )

    assert looks_like_premature_acceptance_success(
        "CONTEXT_PASS",
        messages,
    ) is True


def test_post_tool_workspace_inaccessible_claim_uses_private_compacted_state(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    compacted = (
        "[Compacted prior context]\n"
        "[ACTIVE CONTINUATION STATE]\n"
        "Continue large_context/result.txt for LARGE_CONTEXT_PASS. "
        "The workspace validation already succeeded; write and byte readback remain."
    )
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_list",
                    "type": "function",
                    "function": {
                        "name": "exec_command",
                        "arguments": '{"cmd":"pwd && ls -la large_context"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_list",
            "name": "exec_command",
            "content": "Process exited with code 0\nFinal output: total 0\n",
            "_uwa_compacted_continuation_context": compacted,
        },
    ]
    refusal = (
        "当前运行环境无法访问 /Users/example/acceptance，实际检查结果为 MISSING。"
        "因此无法真实完成 large_context/result.txt 的写入和字节级验证，"
        "也不能返回 LARGE_CONTEXT_PASS。"
    )
    parsed = {"mode": "final", "content": refusal, "tool_calls": []}

    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=refusal,
        parsed=parsed,
    ) is True

def _completed_context_acceptance_history():
    messages = _restart_context_history_after_validation()
    _append_successful_exec(
        messages,
        "call_write_complete",
        "printf '%s\\n' 'EMBER-7319' > context/result.txt",
    )
    _append_successful_exec(
        messages,
        "call_read_complete",
        (
            "python3 -c \"from pathlib import Path; "
            "b=Path('context/result.txt').read_bytes(); "
            "assert b == b'EMBER-7319\\\\n'\""
        ),
        "VALID",
    )
    return messages


def test_completed_acceptance_blocks_redundant_workspace_tool_call(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = _completed_context_acceptance_history()
    raw = (
        '<adapter_calls><call name="exec_command">'
        '<arguments encoding="json"><![CDATA['
        '{"cmd":"mkdir -p context && printf \'%s\\\\n\' \'EMBER-7319\' '
        '> context/result.txt && cat context/result.txt"}'
        ']]></arguments></call></adapter_calls>'
    )
    from app.services.tool_calling_parse import parse_tool_response

    parsed = parse_tool_response(raw, EXEC_TOOLS)

    assert has_redundant_acceptance_tool_call_after_completion(
        messages,
        parsed,
    ) is True
    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=raw,
        parsed=parsed,
    ) is True


def test_completed_acceptance_repairs_descriptive_final_to_exact_sentinel(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = _completed_context_acceptance_history()
    prose = (
        "已完成并验证 context/result.txt，内容正确，命令退出码为 0。"
    )
    parsed = {
        "mode": "final",
        "content": prose,
        "tool_calls": [],
    }

    assert looks_like_acceptance_completion_without_exact_sentinel(
        prose,
        messages,
    ) is True
    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=prose,
        parsed=parsed,
    ) is True


def test_completed_acceptance_roundtrip_rejects_rewrite_and_closes_with_marker(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")
    messages = _completed_context_acceptance_history()
    redundant = (
        '<adapter_calls><call name="exec_command">'
        '<arguments encoding="json"><![CDATA['
        '{"cmd":"mkdir -p context && printf \'%s\\\\n\' \'EMBER-7319\' '
        '> context/result.txt && cat context/result.txt"}'
        ']]></arguments></call></adapter_calls>'
    )
    replies = iter(
        [
            redundant,
            "CONTEXT_PASS",
        ]
    )
    seen = []

    def executor(browser_messages):
        seen.append(browser_messages)
        return next(replies)

    result = complete_tool_calling_roundtrip(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=executor,
    )

    assert result["mode"] == "final"
    assert result["content"] == "CONTEXT_PASS"
    assert result["tool_calls"] == []
    assert len(seen) == 2
    repair = seen[1][1]["content"]
    assert "Do not call any client tool again" in repair
    assert "Do not rewrite context/result.txt" in repair
    assert "Reply with exactly CONTEXT_PASS and nothing else" in repair


def test_completed_acceptance_exact_marker_remains_allowed(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    messages = _completed_context_acceptance_history()
    parsed = {
        "mode": "final",
        "content": "CONTEXT_PASS",
        "tool_calls": [],
    }

    assert looks_like_acceptance_completion_without_exact_sentinel(
        "CONTEXT_PASS",
        messages,
    ) is False
    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text="CONTEXT_PASS",
        parsed=parsed,
    ) is False

