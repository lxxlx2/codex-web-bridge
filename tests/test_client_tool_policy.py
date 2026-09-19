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


def test_repairs_live_missing_exec_command_claim_after_successful_client_call(monkeypatch):
    monkeypatch.setenv(
        "TOOL_CALLING_CLIENT_WORKSPACE_REPAIR",
        "true",
    )

    messages = _successful_read_history()

    refusal = (
        "当前环境缺少你要求的客户端 `exec_command`，"
        "因此无法按该验收协议完成，"
        "也不能声称 `LARGE_CONTEXT_PASS`。"
    )

    parsed = {
        "mode": "final",
        "content": refusal,
        "tool_calls": [],
    }

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


def test_roundtrip_repairs_live_missing_exec_command_claim_into_second_exec(monkeypatch):
    monkeypatch.setenv(
        "TOOL_CALLING_CLIENT_WORKSPACE_REPAIR",
        "true",
    )
    monkeypatch.setenv(
        "TOOL_CALLING_INTERNAL_RETRY_MAX",
        "2",
    )

    replies = iter(
        [
            (
                "当前环境缺少你要求的客户端 `exec_command`，"
                "因此无法按该验收协议完成，"
                "也不能声称 `LARGE_CONTEXT_PASS`。"
            ),
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"printf test > large_context/result.txt '
                '&& cat large_context/result.txt"}'
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
    assert (
        result["tool_calls"][0]["function"]["name"]
        == "exec_command"
    )


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


def test_detects_no_callable_exec_command_claim_before_first_tool_call(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")

    messages = [
        {
            "role": "user",
            "content": (
                "第一步必须通过客户端 exec_command 在当前工作区执行 pwd。"
                "随后创建 context/result.txt 并读取确认。"
            ),
        }
    ]

    refusal = (
        "当前环境没有可调用的 exec_command 客户端函数，"
        "因此我无法真实完成创建和回读 context/result.txt 这两步，"
        "也不能据此回复 CONTEXT_PASS。"
    )

    parsed = {
        "mode": "final",
        "content": refusal,
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=refusal,
        parsed=parsed,
    ) is True

def test_repairs_post_tool_readback_refusal_after_successful_exec(monkeypatch):
    monkeypatch.setenv(
        "TOOL_CALLING_CLIENT_WORKSPACE_REPAIR",
        "true",
    )

    messages = _successful_read_history()

    refusal = (
        "前一步已经通过 exec_command 成功写入结果，"
        "但我现在无法继续使用 exec_command 读取并确认结果，"
        "因此不能完成验收。"
    )

    parsed = {
        "mode": "final",
        "content": refusal,
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=refusal,
        parsed=parsed,
    ) is True


def test_roundtrip_repairs_post_tool_readback_refusal_into_exec(monkeypatch):
    monkeypatch.setenv(
        "TOOL_CALLING_CLIENT_WORKSPACE_REPAIR",
        "true",
    )
    monkeypatch.setenv(
        "TOOL_CALLING_INTERNAL_RETRY_MAX",
        "2",
    )

    replies = iter(
        [
            (
                "前一步已经通过 exec_command 成功写入结果，"
                "但我无法继续使用 exec_command 读取并确认结果，"
                "因此不能完成验收。"
            ),
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"cat context/result.txt"}'
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
    assert (
        result["tool_calls"][0]["function"]["name"]
        == "exec_command"
    )

def test_required_exec_refusal_uses_workspace_repair_before_generic_retry(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")

    replies = iter(
        [
            (
                "当前环境没有可用的客户端 exec_command 工具，"
                "因此无法真实执行 pwd。"
            ),
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"pwd"}'
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
                "content": "必须使用客户端 exec_command 执行 pwd。",
            }
        ],
        tools=EXEC_TOOLS,
        tool_choice={
            "type": "function",
            "name": "exec_command",
        },
        parallel_tool_calls=False,
        round_executor=executor,
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"
    assert len(seen_messages) == 2
    assert "Client Workspace Repair" in seen_messages[1][1]["content"]
    assert "Call exec_command now" in seen_messages[1][1]["content"]


def test_required_exec_repeated_refusal_still_fails_closed(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "1")

    refusal = (
        "当前环境没有可用的客户端 exec_command 工具，"
        "因此无法真实执行 pwd。"
    )

    with pytest.raises(RuntimeError, match="client_workspace_tool_refusal"):
        complete_tool_calling_roundtrip(
            messages=[
                {
                    "role": "user",
                    "content": "必须使用客户端 exec_command 执行 pwd。",
                }
            ],
            tools=EXEC_TOOLS,
            tool_choice={
                "type": "function",
                "name": "exec_command",
            },
            parallel_tool_calls=False,
            round_executor=lambda _messages: refusal,
        )

def test_specific_required_exec_repairs_unmatched_final_text(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")

    messages = [
        {
            "role": "user",
            "content": "Continue the requested operation.",
        }
    ]
    refusal = "I don't have that local command interface in this chat."
    parsed = {
        "mode": "final",
        "content": refusal,
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice={
            "type": "function",
            "name": "exec_command",
        },
        assistant_text=refusal,
        parsed=parsed,
    ) is True


def test_specific_required_exec_repairs_after_latest_user_is_generated_context(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")

    messages = [
        {
            "role": "user",
            "content": "必须使用客户端 exec_command 执行 pwd。",
        },
        {
            "role": "user",
            "content": "<environment_context><cwd>/tmp/project</cwd></environment_context>",
        },
    ]
    refusal = "I cannot perform that operation from here."
    parsed = {
        "mode": "final",
        "content": refusal,
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice={
            "type": "function",
            "name": "exec_command",
        },
        assistant_text=refusal,
        parsed=parsed,
    ) is True


def test_generic_required_does_not_force_workspace_repair(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")

    other_tool = {
        "type": "function",
        "function": {
            "name": "request_user_input",
            "description": "Ask the user a question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                },
                "required": ["question"],
                "additionalProperties": False,
            },
        },
    }
    parsed = {
        "mode": "final",
        "content": "I can answer directly.",
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=[
            {
                "role": "user",
                "content": "Give a normal answer.",
            }
        ],
        tools=[*EXEC_TOOLS, other_tool],
        tool_choice="required",
        assistant_text=parsed["content"],
        parsed=parsed,
    ) is False


def test_specific_required_non_workspace_tool_does_not_force_workspace_repair(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")

    other_tool = {
        "type": "function",
        "function": {
            "name": "request_user_input",
            "description": "Ask the user a question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                },
                "required": ["question"],
                "additionalProperties": False,
            },
        },
    }
    parsed = {
        "mode": "final",
        "content": "I can answer directly.",
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=[
            {
                "role": "user",
                "content": "Give a normal answer.",
            }
        ],
        tools=[*EXEC_TOOLS, other_tool],
        tool_choice={
            "type": "function",
            "name": "request_user_input",
        },
        assistant_text=parsed["content"],
        parsed=parsed,
    ) is False

def test_specific_required_exec_repairs_even_with_prior_tool_history(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")

    messages = _successful_read_history()
    refusal = "I cannot perform the requested command from this chat."
    parsed = {
        "mode": "final",
        "content": refusal,
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice={
            "type": "function",
            "name": "exec_command",
        },
        assistant_text=refusal,
        parsed=parsed,
    ) is True


def test_repair_prompt_preserves_specific_required_workspace_tool():
    apply_patch_tool = {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": "Apply a patch in the local client workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patch": {"type": "string"},
                },
                "required": ["patch"],
                "additionalProperties": False,
            },
        },
    }

    repair = build_client_workspace_repair_messages(
        messages=[{"role": "user", "content": "Apply the requested change."}],
        tools=[*EXEC_TOOLS, apply_patch_tool],
        assistant_text="I cannot perform that operation from here.",
        attempt=1,
        total_attempts=3,
        tool_choice={
            "type": "function",
            "name": "apply_patch",
        },
    )

    assert "Call apply_patch now" in repair[1]["content"]

def _compacted_workspace_messages():
    return [
        {
            "role": "assistant",
            "content": (
                "[Compacted prior context]\n"
                "[DURABLE EXACT STATE]\n"
                "ORBIT-5921\n\n"
                "[ACTIVE CONTINUATION STATE]\n"
                "Workspace validation already succeeded. "
                "The unfinished next step is to use exec_command to write "
                "large_context/result.txt with ORBIT-5921, then use exec_command "
                "again to read and verify the file before replying LARGE_CONTEXT_PASS."
            ),
        },
        {
            "role": "user",
            "content": "Continue from the compacted state and finish the pending task.",
        },
    ]


def test_repairs_tool_unavailable_claim_after_recursive_compaction(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")

    refusal = (
        "当前 ChatGPT 会话本身不会新增 exec_command 工具。"
        "虽然 ORBIT-5921 已从压缩状态恢复，但我不能真实写入并读取结果文件。"
    )

    parsed = {
        "mode": "final",
        "content": refusal,
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=_compacted_workspace_messages(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=refusal,
        parsed=parsed,
    ) is True


def test_roundtrip_repairs_recursive_compaction_refusal_into_next_exec(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")

    replies = iter(
        [
            (
                "当前 ChatGPT 会话里没有 exec_command，"
                "所以即使记得 ORBIT-5921 也无法真实写入并回读结果文件。"
            ),
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"echo ORBIT-5921 > large_context/result.txt '
                '&& cat large_context/result.txt"}'
                ']]></arguments></call></adapter_calls>'
            ),
        ]
    )

    result = complete_tool_calling_roundtrip(
        messages=_compacted_workspace_messages(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=lambda _messages: next(replies),
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"


def test_completed_only_compaction_does_not_force_workspace_repair(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")

    messages = [
        {
            "role": "assistant",
            "content": (
                "[Compacted prior context]\n"
                "[DURABLE EXACT STATE]\n"
                "NONE\n\n"
                "[ACTIVE CONTINUATION STATE]\n"
                "The earlier calc.py workspace repair and tests are completed. "
                "The current task is to answer a conceptual Python question."
            ),
        },
        {
            "role": "user",
            "content": "Explain Python descriptors conceptually.",
        },
    ]

    parsed = {
        "mode": "final",
        "content": "Python descriptors customize attribute access.",
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=parsed["content"],
        parsed=parsed,
    ) is False

def test_recursive_compaction_repair_prompt_keeps_exact_state():
    repair = build_client_workspace_repair_messages(
        messages=_compacted_workspace_messages(),
        tools=EXEC_TOOLS,
        assistant_text=(
            "当前会话没有 exec_command，"
            "因此无法继续完成工作区写入。"
        ),
        attempt=1,
        total_attempts=3,
        tool_choice="auto",
    )

    user = repair[1]["content"]

    assert "Compacted continuation state already present" in user
    assert "ORBIT-5921" in user
    assert "large_context/result.txt" in user
    assert "Continue the task by calling exec_command again" not in user
    assert "Call exec_command now" in user

LIVE_RECURSIVE_COMPACTION_REFUSAL = (
    "这段内容只是你粘贴到对话里的文本，无法把其中声明的 "
    "`exec_command` / `write_stdin` 变成我当前会话实际可调用的客户端工具。\n\n"
    "因此当前验收状态仍然是：\n\n"
    "- 精确值：`ORBIT-5921`\n"
    "- 目标文件：`large_context/result.txt`\n"
    "- 要求：必须通过你本地客户端的 `exec_command` 创建，再次读取验证\n"
    "- 成功后才可返回：`LARGE_CONTEXT_PASS`\n\n"
    "我当前没有那个本地 Codex adapter 的 `exec_command` 执行入口，所以不能伪造通过结果。"
)


def test_detects_exact_live_recursive_compaction_tool_entry_refusal(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")

    parsed = {
        "mode": "final",
        "content": LIVE_RECURSIVE_COMPACTION_REFUSAL,
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=_compacted_workspace_messages(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=LIVE_RECURSIVE_COMPACTION_REFUSAL,
        parsed=parsed,
    ) is True


def test_roundtrip_repairs_exact_live_recursive_compaction_refusal(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")

    replies = iter(
        [
            LIVE_RECURSIVE_COMPACTION_REFUSAL,
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"echo ORBIT-5921 > large_context/result.txt '
                '&& cat large_context/result.txt"}'
                ']]></arguments></call></adapter_calls>'
            ),
        ]
    )

    result = complete_tool_calling_roundtrip(
        messages=_compacted_workspace_messages(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=lambda _messages: next(replies),
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"

def test_required_exec_repair_prompt_explains_adapter_transport_and_no_prose():
    repair = build_client_workspace_repair_messages(
        messages=[
            {
                "role": "user",
                "content": (
                    "第一步必须通过客户端 exec_command 在当前工作区执行 "
                    "pwd && test -f .uwa_codex_acceptance && test -d context。"
                ),
            }
        ],
        tools=EXEC_TOOLS,
        assistant_text=(
            "当前 ChatGPT 会话没有实际可调用的 exec_command，"
            "因此无法执行。"
        ),
        attempt=2,
        total_attempts=4,
        tool_choice={
            "type": "function",
            "name": "exec_command",
        },
    )

    system = repair[0]["content"]
    user = repair[1]["content"]

    assert "adapter_calls response is the transport" in system
    assert "real invocation request" in system
    assert "protocol contract, not a suggestion" in user
    assert "next response must be one executable client-tool call" in user
    assert "Return exactly one exec_command call now and no prose" in user
    assert "pwd && test -f .uwa_codex_acceptance && test -d context" in user


def test_specific_required_exec_gets_one_extra_repair_attempt(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "1")

    refusal = (
        "当前 ChatGPT 会话没有实际可调用的 exec_command，"
        "因此无法执行本地工作区命令。"
    )
    replies = iter(
        [
            refusal,
            refusal,
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"pwd && test -f .uwa_codex_acceptance && test -d context"}'
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
                "content": (
                    "第一步必须通过客户端 exec_command 在当前工作区执行 "
                    "pwd && test -f .uwa_codex_acceptance && test -d context。"
                ),
            }
        ],
        tools=EXEC_TOOLS,
        tool_choice={
            "type": "function",
            "name": "exec_command",
        },
        parallel_tool_calls=False,
        round_executor=executor,
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"
    assert len(seen) == 3
    assert "Attempt: 2/3" in seen[2][1]["content"]
    assert "next response must be one executable client-tool call" in seen[2][1]["content"]

LIVE_POST_COMPACTION_MISSING_TASK_REPLY = (
    "请继续发送这一轮需要我执行的具体任务或验证步骤。"
)


def test_detects_live_post_compaction_missing_task_clarification(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")

    parsed = {
        "mode": "final",
        "content": LIVE_POST_COMPACTION_MISSING_TASK_REPLY,
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=_compacted_workspace_messages(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=LIVE_POST_COMPACTION_MISSING_TASK_REPLY,
        parsed=parsed,
    ) is True


def test_live_missing_task_clarification_repairs_into_exec(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")

    replies = iter(
        [
            LIVE_POST_COMPACTION_MISSING_TASK_REPLY,
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"echo ORBIT-5921 > large_context/result.txt '
                '&& cat large_context/result.txt"}'
                ']]></arguments></call></adapter_calls>'
            ),
        ]
    )

    seen = []

    result = complete_tool_calling_roundtrip(
        messages=_compacted_workspace_messages(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=lambda browser_messages: (
            seen.append(browser_messages)
            or next(replies)
        ),
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"
    assert len(seen) == 2
    assert "already recorded in the compacted continuation state" in seen[1][1]["content"]
    assert "ORBIT-5921" in seen[1][1]["content"]
    assert "large_context/result.txt" in seen[1][1]["content"]
    assert "Do not ask" not in seen[1][1]["content"] or "task" in seen[1][1]["content"]


def test_missing_task_clarification_without_compacted_workspace_state_is_not_forced(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")

    parsed = {
        "mode": "final",
        "content": LIVE_POST_COMPACTION_MISSING_TASK_REPLY,
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=[
            {
                "role": "user",
                "content": "我们先聊一下后续计划。",
            }
        ],
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=LIVE_POST_COMPACTION_MISSING_TASK_REPLY,
        parsed=parsed,
    ) is False

def _successful_acceptance_workspace_validation_history():
    return [
        {
            "role": "assistant",
            "content": (
                "[Compacted prior context]\n"
                "[DURABLE EXACT STATE]\n"
                "ORBIT-5921\n\n"
                "[ACTIVE CONTINUATION STATE]\n"
                "The exact workspace validation command must run first. "
                "If it succeeds, write ORBIT-5921 plus one newline to "
                "large_context/result.txt, then read it back with exec_command, "
                "and only then reply LARGE_CONTEXT_PASS."
            ),
        },
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
                            '&& test -d large_context"}'
                        ),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_validate",
            "name": "exec_command",
            "content": (
                "Process exited with code 0\n"
                "Final output:\n"
                "/Users/jerson/uwa-codex-acceptance\n"
            ),
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_inspect",
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
            "tool_call_id": "call_inspect",
            "name": "exec_command",
            "content": (
                "Process exited with code 0\n"
                "Final output:\n"
                "/Users/jerson/uwa-codex-acceptance\n"
                "total 0\n"
            ),
        },
    ]


def test_repairs_false_acceptance_workspace_mismatch_after_successful_validation(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")

    parsed = {
        "mode": "final",
        "content": "ACCEPTANCE_WORKSPACE_MISMATCH",
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=_successful_acceptance_workspace_validation_history(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=parsed["content"],
        parsed=parsed,
    ) is True


def test_false_acceptance_workspace_mismatch_repairs_into_pending_write(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")

    replies = iter(
        [
            "ACCEPTANCE_WORKSPACE_MISMATCH",
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"echo ORBIT-5921 > large_context/result.txt '
                '&& cat large_context/result.txt"}'
                ']]></arguments></call></adapter_calls>'
            ),
        ]
    )

    seen = []
    result = complete_tool_calling_roundtrip(
        messages=_successful_acceptance_workspace_validation_history(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=lambda browser_messages: (
            seen.append(browser_messages)
            or next(replies)
        ),
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"
    assert len(seen) == 2
    assert "completed with exit code 0" in seen[1][1]["content"]
    assert "ORBIT-5921" in seen[1][1]["content"]
    assert "large_context/result.txt" in seen[1][1]["content"]


def test_real_failed_acceptance_workspace_validation_keeps_mismatch_sentinel(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")

    messages = _successful_acceptance_workspace_validation_history()
    messages[2] = {
        "role": "tool",
        "tool_call_id": "call_validate",
        "name": "exec_command",
        "content": "Process exited with code 1\nFinal output:\n",
    }

    parsed = {
        "mode": "final",
        "content": "ACCEPTANCE_WORKSPACE_MISMATCH",
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=parsed["content"],
        parsed=parsed,
    ) is False

def _successful_restart_workspace_validation_history():
    return [
        {
            "role": "user",
            "content": (
                "这是同一个 Codex 对话的第二轮重启恢复验收。"
                "第一步必须通过客户端 exec_command 在当前工作区执行 "
                "pwd && test -f .uwa_codex_acceptance && test -d context。"
                "如果工作区校验失败，只回复 ACCEPTANCE_WORKSPACE_MISMATCH。"
                "校验成功后，只使用上一轮对话上下文中记住的令牌，"
                "通过客户端 exec_command 创建 context/result.txt，"
                "随后再次读取并确认该文件。完成后只回复 CONTEXT_PASS。"
            ),
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_restart_validate",
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
            "tool_call_id": "call_restart_validate",
            "name": "exec_command",
            "content": (
                "Process exited with code 0\n"
                "Final output:\n"
                "/Users/jerson/uwa-codex-acceptance\n"
            ),
        },
    ]


def test_repairs_false_restart_workspace_mismatch_after_successful_validation(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")

    parsed = {
        "mode": "final",
        "content": "ACCEPTANCE_WORKSPACE_MISMATCH",
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=_successful_restart_workspace_validation_history(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=parsed["content"],
        parsed=parsed,
    ) is True


def test_false_restart_workspace_mismatch_repairs_into_pending_context_write(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")
    monkeypatch.setenv("TOOL_CALLING_INTERNAL_RETRY_MAX", "2")

    replies = iter(
        [
            "ACCEPTANCE_WORKSPACE_MISMATCH",
            (
                '<adapter_calls><call name="exec_command">'
                '<arguments encoding="json"><![CDATA['
                '{"cmd":"echo CONTEXT-REMEMBERED > context/result.txt '
                '&& cat context/result.txt"}'
                ']]></arguments></call></adapter_calls>'
            ),
        ]
    )

    seen = []
    result = complete_tool_calling_roundtrip(
        messages=_successful_restart_workspace_validation_history(),
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
        round_executor=lambda browser_messages: (
            seen.append(browser_messages)
            or next(replies)
        ),
    )

    assert result["mode"] == "tool_calls"
    assert result["tool_calls"][0]["function"]["name"] == "exec_command"
    assert len(seen) == 2
    assert "completed with exit code 0" in seen[1][1]["content"]
    assert "current acceptance request" in seen[1][1]["content"]
    assert "context/result.txt" in seen[1][1]["content"]


def test_real_failed_restart_workspace_validation_keeps_mismatch_sentinel(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "true")

    messages = _successful_restart_workspace_validation_history()
    messages[2] = {
        "role": "tool",
        "tool_call_id": "call_restart_validate",
        "name": "exec_command",
        "content": "Process exited with code 1\nFinal output:\n",
    }

    parsed = {
        "mode": "final",
        "content": "ACCEPTANCE_WORKSPACE_MISMATCH",
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=messages,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        assistant_text=parsed["content"],
        parsed=parsed,
    ) is False

