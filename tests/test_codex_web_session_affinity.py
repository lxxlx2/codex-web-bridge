from __future__ import annotations

import json

from app.api.chat import ResponsesRequest
from app.api.codex_responses_v2 import (
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
