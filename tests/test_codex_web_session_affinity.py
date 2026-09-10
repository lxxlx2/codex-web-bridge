from __future__ import annotations

import json

from app.api.chat import ChatRequest, ResponsesRequest
from app.api.codex_responses_v2 import (
    _browser_delta_chat_request,
    _browser_delta_request,
    _clone_for_required_tool_retry,
    _response_id_from_sse,
)
from app.core.tab_pool import TabSession
from app.services import codex_web_session_affinity as affinity


def _clear_bindings():
    with affinity._BINDINGS_LOCK:
        affinity._BINDINGS.clear()


def test_affinity_binding_matches_model_and_reasoning(monkeypatch):
    _clear_bindings()
    monkeypatch.setenv("UWA_CODEX_WEB_SESSION_AFFINITY", "true")

    assert affinity.bind_response_to_conversation(
        "resp_one",
        "/c/WEB:12345678-abcd",
        model="GPT-5.6 Sol",
        reasoning="high",
    )

    binding = affinity.resolve_conversation_binding(
        "resp_one",
        model="GPT-5.6 Sol",
        reasoning="high",
    )
    assert binding is not None
    assert binding.pathname == "/c/WEB:12345678-abcd"

    assert affinity.resolve_conversation_binding(
        "resp_one",
        model="GPT-5.6 Sol",
        reasoning="medium",
    ) is None
    assert affinity.resolve_conversation_binding(
        "resp_one",
        model="another-model",
        reasoning="high",
    ) is None


def test_affinity_rejects_non_chatgpt_paths(monkeypatch):
    _clear_bindings()
    monkeypatch.setenv("UWA_CODEX_WEB_SESSION_AFFINITY", "true")

    assert not affinity.bind_response_to_conversation(
        "resp_bad",
        "https://example.com/c/12345678",
        model="GPT-5.6 Sol",
        reasoning="high",
    )
    assert not affinity.bind_response_to_conversation(
        "resp_bad2",
        "/settings",
        model="GPT-5.6 Sol",
        reasoning="high",
    )


def test_codex_reuse_hint_overrides_generic_new_chat_policy():
    affinity.install_codex_workflow_reuse_policy()
    session = TabSession(id="test", tab=object())
    setattr(session, "_codex_web_affinity_reuse", True)

    assert session.should_start_new_conversation(
        current_domain="chatgpt.com",
        preset_name="main",
        threshold_seconds=0,
        force_new=False,
    ) is False


def test_browser_delta_removes_server_history_handles_only():
    body = ResponsesRequest(
        model="chatgpt",
        instructions="large codex instructions",
        previous_response_id="resp_prev",
        input=[
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": "/workspace",
            }
        ],
        stream=True,
        tools=[
            {
                "type": "function",
                "name": "exec_command",
                "description": "run command",
                "parameters": {"type": "object"},
            }
        ],
    )

    delta = _browser_delta_request(body)
    assert delta.previous_response_id is None
    assert delta.instructions is None
    assert delta.input == body.input
    assert delta.tools == body.tools


def test_required_tool_retry_is_incremental_and_chained():
    body = ResponsesRequest(
        model="chatgpt",
        instructions="original instructions",
        input=[{"role": "user", "content": "must use exec_command"}],
        stream=True,
        tools=[
            {
                "type": "function",
                "name": "exec_command",
                "description": "run command",
                "parameters": {"type": "object"},
            }
        ],
    )

    retry = _clone_for_required_tool_retry(
        body,
        "exec_command",
        2,
        previous_response_id="resp_attempt_one",
    )
    assert retry.previous_response_id == "resp_attempt_one"
    assert retry.instructions is None
    assert isinstance(retry.input, list) and len(retry.input) == 1
    assert retry.input[0]["role"] == "user"
    assert "exec_command" in retry.input[0]["content"]
    assert retry.tool_choice == {"type": "function", "name": "exec_command"}


def test_response_id_is_recovered_from_minimal_sse():
    created = {
        "type": "response.created",
        "sequence_number": 1,
        "response": {"id": "resp_live_123", "status": "in_progress"},
    }
    chunks = [
        "event: response.created\n"
        + "data: "
        + json.dumps(created)
        + "\n\n"
    ]
    assert _response_id_from_sse(chunks) == "resp_live_123"


def test_browser_delta_chat_request_preserves_tool_provenance():
    tools = [
        {
            "type": "function",
            "name": "exec_command",
            "description": "Run a command in the client workspace.",
            "parameters": {
                "type": "object",
                "properties": {"cmd": {"type": "string"}},
                "required": ["cmd"],
            },
        }
    ]

    incoming = ResponsesRequest(
        model="chatgpt",
        previous_response_id="resp_previous",
        input=[
            {
                "type": "function_call_output",
                "call_id": "call_write",
                "output": "Process exited with code 0",
            }
        ],
        stream=True,
        tools=tools,
    )

    state_chat = ChatRequest(
        model="chatgpt",
        messages=[
            {
                "role": "user",
                "content": (
                    "Use exec_command to create context/result.txt, "
                    "then read it and confirm the result."
                ),
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_write",
                        "type": "function",
                        "function": {
                            "name": "exec_command",
                            "arguments": '{"cmd":"printf test > context/result.txt"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_write",
                "name": "exec_command",
                "content": "Process exited with code 0",
            },
        ],
        stream=False,
    )

    delta = _browser_delta_chat_request(state_chat, incoming)

    assert len(delta.messages) == 2
    assert delta.messages[0]["role"] == "assistant"
    assert delta.messages[0]["tool_calls"][0]["id"] == "call_write"
    assert (
        delta.messages[0]["tool_calls"][0]["function"]["name"]
        == "exec_command"
    )
    assert delta.messages[1]["role"] == "tool"
    assert delta.messages[1]["tool_call_id"] == "call_write"


def test_affinity_tool_result_delta_enables_post_tool_workspace_repair():
    from app.services.client_tool_policy import (
        should_repair_client_workspace_refusal,
    )

    incoming = ResponsesRequest(
        model="chatgpt",
        previous_response_id="resp_previous",
        input=[
            {
                "type": "function_call_output",
                "call_id": "call_write",
                "output": "Process exited with code 0",
            }
        ],
        stream=True,
        tools=[
            {
                "type": "function",
                "name": "exec_command",
                "description": "Run a command in the local client workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {"cmd": {"type": "string"}},
                    "required": ["cmd"],
                },
            }
        ],
    )

    state_chat = ChatRequest(
        model="chatgpt",
        messages=[
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_write",
                        "type": "function",
                        "function": {
                            "name": "exec_command",
                            "arguments": '{"cmd":"echo ok"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_write",
                "name": "exec_command",
                "content": "Process exited with code 0",
            },
        ],
        stream=False,
    )

    delta = _browser_delta_chat_request(state_chat, incoming)

    refusal = (
        "当前环境没有实际暴露 `exec_command` 客户端函数，"
        "因此无法执行最后一次读取校验。"
    )

    parsed = {
        "mode": "final",
        "content": refusal,
        "tool_calls": [],
    }

    assert should_repair_client_workspace_refusal(
        messages=delta.messages,
        tools=delta.tools or [],
        tool_choice=delta.tool_choice,
        assistant_text=refusal,
        parsed=parsed,
    ) is True
