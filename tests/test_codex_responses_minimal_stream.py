import json

from fastapi import HTTPException

from app.api.chat import ResponsesRequest
from app.api import codex_responses as codex_responses_module
from app.api.codex_responses import (
    _codex_event,
    _codex_wire_item,
    _hydrate_codex_continuation,
    _sanitize_codex_tool_payload,
)


def _tool_payload(content="I cannot access exec_command"):
    return {
        "model": "chatgpt",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": "call_test",
                            "type": "function",
                            "function": {
                                "name": "exec_command",
                                "arguments": '{"cmd":"cat calc.py"}',
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {},
    }


def test_tool_payload_drops_contradictory_visible_text():
    clean = _sanitize_codex_tool_payload(_tool_payload())
    message = clean["choices"][0]["message"]
    assert message["content"] is None
    assert message["tool_calls"][0]["function"]["name"] == "exec_command"


def test_plain_final_text_is_preserved():
    payload = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "done"},
            }
        ]
    }
    clean = _sanitize_codex_tool_payload(payload)
    assert clean["choices"][0]["message"]["content"] == "done"


def test_function_call_wire_item_matches_codex_minimal_shape():
    wire = _codex_wire_item(
        {
            "id": "fc_test",
            "type": "function_call",
            "status": "completed",
            "call_id": "call_test",
            "name": "exec_command",
            "arguments": '{"cmd":"cat calc.py"}',
        }
    )
    assert wire == {
        "type": "function_call",
        "call_id": "call_test",
        "name": "exec_command",
        "arguments": '{"cmd":"cat calc.py"}',
    }


def test_codex_output_item_done_event_contains_parseable_function_call():
    event = _codex_event(
        "response.output_item.done",
        sequence_number=2,
        output_index=0,
        item={
            "type": "function_call",
            "call_id": "call_test",
            "name": "exec_command",
            "arguments": '{"cmd":"cat calc.py"}',
        },
    )
    assert event.startswith("event: response.output_item.done\n")
    data_line = next(line for line in event.splitlines() if line.startswith("data: "))
    payload = json.loads(data_line[len("data: ") :])
    assert payload["type"] == "response.output_item.done"
    assert payload["item"]["type"] == "function_call"
    assert payload["item"]["name"] == "exec_command"
    assert payload["item"]["call_id"] == "call_test"


def test_missing_process_state_restores_private_persisted_history(monkeypatch):
    def _missing(_response_id):
        raise HTTPException(status_code=404, detail="missing")

    persisted = [
        {"role": "user", "content": "inspect calc.py"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_test",
                    "type": "function",
                    "function": {
                        "name": "exec_command",
                        "arguments": '{"cmd":"cat calc.py"}',
                    },
                }
            ],
        },
    ]
    monkeypatch.setattr(codex_responses_module, "_load_responses_state", _missing)
    monkeypatch.setattr(
        codex_responses_module,
        "load_response_messages",
        lambda _response_id: persisted,
    )

    body = ResponsesRequest(
        model="chatgpt",
        previous_response_id="resp_old",
        input=[
            {
                "type": "function_call_output",
                "call_id": "call_test",
                "output": "def add(a, b): return a - b",
            }
        ],
    )
    restored = _hydrate_codex_continuation(body)

    assert restored.previous_response_id is None
    assert restored.input[:2] == persisted
    assert restored.input[-1]["type"] == "function_call_output"
    assert body.previous_response_id == "resp_old"


def test_missing_all_state_still_fails_for_delta_only_turn(monkeypatch):
    def _missing(_response_id):
        raise HTTPException(status_code=404, detail="missing")

    monkeypatch.setattr(codex_responses_module, "_load_responses_state", _missing)
    monkeypatch.setattr(
        codex_responses_module,
        "load_response_messages",
        lambda _response_id: None,
    )
    body = ResponsesRequest(
        model="chatgpt",
        previous_response_id="resp_old",
        input=[
            {
                "type": "function_call_output",
                "call_id": "call_test",
                "output": "tool result",
            }
        ],
    )

    try:
        _hydrate_codex_continuation(body)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("delta-only turn must fail when no continuation state exists")
