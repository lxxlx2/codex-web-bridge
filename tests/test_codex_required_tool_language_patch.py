from app.api.chat import ResponsesRequest
from app.api import codex_responses_v2 as v2
from app.services.codex_required_tool_language_patch import (
    client_imperative_required_tool_pattern,
    client_prefixed_required_tool_pattern,
    install_codex_required_tool_language_patch,
)


def _tool(name: str):
    return {
        "type": "function",
        "name": name,
        "description": f"test {name}",
        "parameters": {
            "type": "object",
            "properties": {"cmd": {"type": "string"}},
            "required": ["cmd"],
        },
    }


def _body(text: str):
    return ResponsesRequest(
        model="chatgpt",
        stream=True,
        input=[
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            }
        ],
        tools=[_tool("exec_command"), _tool("write_stdin")],
    )


def test_pattern_matches_stage_c_workspace_guard_wording():
    pattern = client_prefixed_required_tool_pattern()
    match = pattern.search(
        "第一步必须通过客户端 exec_command 在当前 Codex 工作区执行 pwd。"
    )
    assert match is not None
    assert match.group(1) == "exec_command"


def test_pattern_matches_post_remote_recovery_wording():
    pattern = client_prefixed_required_tool_pattern()
    match = pattern.search(
        "第一步必须单独调用一次客户端 exec_command，只执行 pwd。"
    )
    assert match is not None
    assert match.group(1) == "exec_command"


def test_pattern_matches_h3_first_use_english_wording():
    pattern = client_imperative_required_tool_pattern()
    match = pattern.search("First use exec_command to run:\npwd\ngit status --short")
    assert match is not None
    assert match.group(1) == "exec_command"


def test_pattern_matches_local_client_english_wording():
    pattern = client_imperative_required_tool_pattern()
    match = pattern.search(
        "First use the local client exec_command tool to run:\npwd\ngit status --short"
    )
    assert match is not None
    assert match.group(1) == "exec_command"


def test_installed_detector_requires_real_exec_for_stage_c_workspace_guard():
    install_codex_required_tool_language_patch()
    body = _body(
        "第一步必须通过客户端 exec_command 在当前 Codex 工作区执行 "
        "pwd && test -f .uwa_codex_acceptance && test -d git_diff。"
    )
    assert v2.required_declared_tool(body) == "exec_command"


def test_installed_detector_requires_real_exec_for_post_remote_recovery_wording():
    install_codex_required_tool_language_patch()
    body = _body(
        "第一步必须单独调用一次客户端 exec_command，只执行 "
        "pwd && test -f .uwa_codex_acceptance && test -d large_context。"
    )
    assert v2.required_declared_tool(body) == "exec_command"


def test_installed_detector_requires_real_exec_for_h3_english_wording():
    install_codex_required_tool_language_patch()
    body = _body(
        "This is the live H3 handoff acceptance.\n\n"
        "First use exec_command to run:\n\n"
        "pwd\n"
        "git status --short\n"
        "cat effects.log"
    )
    assert v2.required_declared_tool(body) == "exec_command"


def test_installed_detector_requires_real_exec_for_local_client_english_wording():
    install_codex_required_tool_language_patch()
    body = _body(
        "First use the local client exec_command tool to run:\n"
        "pwd\n"
        "git branch --show-current"
    )
    assert v2.required_declared_tool(body) == "exec_command"


def test_plain_client_tool_reference_still_does_not_force_execution():
    install_codex_required_tool_language_patch()
    body = _body("解释客户端 exec_command 在这个协议中有什么作用。")
    assert v2.required_declared_tool(body) == ""


def test_explanatory_must_not_overmatch_required_tool():
    install_codex_required_tool_language_patch()
    body = _body("你必须解释为什么 exec_command 在客户端执行，而不是网页执行。")
    assert v2.required_declared_tool(body) == ""


def test_explanatory_english_reference_does_not_force_execution():
    install_codex_required_tool_language_patch()
    body = _body("Explain when to use exec_command in this protocol.")
    assert v2.required_declared_tool(body) == ""

def test_desktop_generated_trailing_user_context_does_not_hide_required_exec():
    install_codex_required_tool_language_patch()
    body = ResponsesRequest(
        model="chatgpt",
        stream=True,
        input=[
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "desktop instructions"}],
            },
            {
                "type": "message",
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": (
                        "第一步必须通过客户端 exec_command 在当前 Codex 工作区执行 "
                        "pwd && test -f .uwa_codex_acceptance && test -d multi_file。"
                    ),
                }],
            },
            {
                "type": "message",
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": "<environment_context><cwd>/tmp/project</cwd></environment_context>",
                }],
            },
        ],
        tools=[_tool("exec_command"), _tool("write_stdin")],
    )

    assert v2.required_declared_tool(body) == "exec_command"


def test_historical_required_exec_does_not_leak_past_assistant_boundary():
    install_codex_required_tool_language_patch()
    body = ResponsesRequest(
        model="chatgpt",
        stream=True,
        input=[
            {
                "type": "message",
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": "必须通过客户端 exec_command 执行 pwd。",
                }],
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "done"}],
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "解释刚才发生了什么。"}],
            },
            {
                "type": "message",
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": "<environment_context><cwd>/tmp/project</cwd></environment_context>",
                }],
            },
        ],
        tools=[_tool("exec_command"), _tool("write_stdin")],
    )

    assert v2.required_declared_tool(body) == ""

def test_detector_accepts_markdown_escaped_desktop_tool_name():
    install_codex_required_tool_language_patch()
    body = _body("必须使用客户端 exec\\_command 执行 pwd。")
    assert v2.required_declared_tool(body) == "exec_command"


def test_detector_accepts_zero_width_desktop_tool_name():
    install_codex_required_tool_language_patch()
    body = _body("必须使用客户端 exec\u200b_command 执行 pwd。")
    assert v2.required_declared_tool(body) == "exec_command"


def test_detector_accepts_display_spaced_desktop_tool_name():
    install_codex_required_tool_language_patch()
    body = _body("必须使用客户端 exec command 执行 pwd。")
    assert v2.required_declared_tool(body) == "exec_command"


def test_normalized_detector_preserves_explanatory_non_requirement():
    install_codex_required_tool_language_patch()
    body = _body("你必须解释为什么 exec\\_command 在客户端执行。")
    assert v2.required_declared_tool(body) == ""

