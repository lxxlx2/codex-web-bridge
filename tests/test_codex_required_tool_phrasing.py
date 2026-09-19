from types import SimpleNamespace

from app.api.codex_responses_v2 import required_declared_tool


TOOLS = [
    {
        "type": "function",
        "name": "exec_command",
        "description": "Execute a local command in the client sandbox.",
        "parameters": {"type": "object", "properties": {}},
    }
]


def _body(text: str):
    return SimpleNamespace(
        tools=TOOLS,
        tool_choice="auto",
        input=[{"role": "user", "content": text}],
    )


def test_required_tool_accepts_real_h3_qualified_phrase():
    assert (
        required_declared_tool(
            _body("You must use the local exec_command tool. Run exactly pwd.")
        )
        == "exec_command"
    )


def test_required_tool_accepts_imperative_client_phrase():
    assert (
        required_declared_tool(
            _body("First use the local client exec_command tool to inspect the workspace.")
        )
        == "exec_command"
    )


def test_required_tool_accepts_direct_imperative_phrase():
    assert required_declared_tool(_body("Call exec_command now.")) == "exec_command"


def test_required_tool_does_not_promote_explanatory_optional_phrase():
    assert (
        required_declared_tool(
            _body("The documentation says you can use the local exec_command tool if available.")
        )
        == ""
    )
