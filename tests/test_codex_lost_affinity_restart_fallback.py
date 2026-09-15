from fastapi import HTTPException

from app.api.chat import ResponsesRequest
from app.api import codex_responses as legacy
from app.api import codex_responses_v2 as v2


def _tool():
    return {
        "type": "function",
        "name": "exec_command",
        "description": "run local command",
        "parameters": {"type": "object"},
    }


def test_lost_affinity_restart_fallback_hydrates_persisted_history(monkeypatch):
    persisted = [
        {"role": "user", "content": "remember synthetic context"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_old",
                    "type": "function",
                    "function": {
                        "name": "exec_command",
                        "arguments": '{"cmd":"pwd"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_old",
            "content": "/workspace",
        },
    ]
    incoming = ResponsesRequest(
        model="chatgpt",
        previous_response_id="resp_before_restart",
        input=[
            {
                "type": "function_call_output",
                "call_id": "call_next",
                "output": "next-result",
            }
        ],
        stream=True,
        tools=[_tool()],
        reasoning={"effort": "high"},
    )

    def missing_process_local_state(_response_id):
        raise HTTPException(status_code=404, detail="missing after restart")

    monkeypatch.setattr(legacy, "_load_responses_state", missing_process_local_state)
    monkeypatch.setattr(legacy, "load_response_messages", lambda response_id: persisted)
    monkeypatch.setattr(v2, "resolve_conversation_binding", lambda *args, **kwargs: None)
    monkeypatch.setattr(v2, "prepare_and_verify_codex_web_mode", lambda reasoning: None)
    monkeypatch.setattr(v2, "install_codex_chatgpt_network_tuning", lambda: None)
    monkeypatch.setattr(v2, "normalize_codex_reasoning", lambda reasoning: "high")
    monkeypatch.setattr(v2, "target_web_model", lambda: "GPT-5.6 Sol")

    hydrated, reused, reused_path, reasoning = v2._prepare_codex_web_turn(incoming)

    assert reused is False
    assert reused_path == ""
    assert reasoning == "high"
    assert hydrated.previous_response_id is None
    assert hydrated.input[: len(persisted)] == persisted
    assert hydrated.input[-1] == incoming.input[0]


def test_missing_affinity_without_persisted_or_replayable_history_fails_closed(monkeypatch):
    incoming = ResponsesRequest(
        model="chatgpt",
        previous_response_id="resp_missing_everywhere",
        input=[
            {
                "type": "function_call_output",
                "call_id": "orphan_call",
                "output": "unknown-effect",
            }
        ],
        stream=True,
        tools=[_tool()],
        reasoning={"effort": "high"},
    )

    def missing_process_local_state(_response_id):
        raise HTTPException(status_code=404, detail="missing after restart")

    monkeypatch.setattr(legacy, "_load_responses_state", missing_process_local_state)
    monkeypatch.setattr(legacy, "load_response_messages", lambda response_id: None)
    monkeypatch.setattr(v2, "resolve_conversation_binding", lambda *args, **kwargs: None)
    monkeypatch.setattr(v2, "prepare_and_verify_codex_web_mode", lambda reasoning: None)
    monkeypatch.setattr(v2, "install_codex_chatgpt_network_tuning", lambda: None)
    monkeypatch.setattr(v2, "normalize_codex_reasoning", lambda reasoning: "high")
    monkeypatch.setattr(v2, "target_web_model", lambda: "GPT-5.6 Sol")

    try:
        v2._prepare_codex_web_turn(incoming)
    except HTTPException as exc:
        assert exc.status_code == 404
        assert "previous_response_id not found or expired" in str(exc.detail)
    else:
        raise AssertionError("orphan function_call_output must fail closed")
