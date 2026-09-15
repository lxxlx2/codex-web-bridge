from app.services import client_tool_policy as policy
from app.services.codex_workspace_refusal_language_patch import (
    install_codex_workspace_refusal_language_patch,
    looks_like_codex_workspace_path_refusal,
)


def _exec_tool():
    return {
        "type": "function",
        "function": {
            "name": "exec_command",
            "description": "Run a command in the client workspace",
            "parameters": {"type": "object"},
        },
    }


def test_live_stage_e_path_refusal_wording_is_detected():
    text = (
        "无法回复 CONTEXT_PASS：当前可用执行环境中不存在 "
        "`/Users/jerson/uwa-codex-acceptance`，因此没有实际完成并读取 "
        "`context/result.txt`。"
    )
    assert looks_like_codex_workspace_path_refusal(text)


def test_explanatory_path_text_is_not_treated_as_refusal():
    text = "当前执行环境的工作目录示例可以写成 /Users/example/project。"
    assert not looks_like_codex_workspace_path_refusal(text)


def test_installed_patch_drives_existing_client_workspace_repair_policy():
    install_codex_workspace_refusal_language_patch()
    messages = [
        {
            "role": "user",
            "content": (
                "使用上一轮上下文记住的令牌，创建 context/result.txt，"
                "然后实际读取文件确认内容，并回复 CONTEXT_PASS。"
            ),
        }
    ]
    refusal = (
        "当前可用执行环境中不存在 `/Users/jerson/uwa-codex-acceptance`，"
        "因此没有实际完成并读取 `context/result.txt`。"
    )

    assert policy.should_repair_client_workspace_refusal(
        messages=messages,
        tools=[_exec_tool()],
        tool_choice="auto",
        assistant_text=refusal,
        parsed={"mode": "final", "content": refusal, "tool_calls": []},
    )
