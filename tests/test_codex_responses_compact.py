import asyncio
import json
from types import SimpleNamespace

import app.api.codex_compact as compact_module
from app.api.codex_compact import (
    CodexCompactRequest,
    compact_output_items,
    compact_request_to_responses,
    router,
)


def _history():
    return [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Keep constraint ALPHA."}],
        },
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Working on it."}],
        },
    ]


class _SingleArgumentLogger:
    def __init__(self):
        self.info_messages = []
        self.warning_messages = []

    def info(self, message):
        self.info_messages.append(message)

    def warning(self, message):
        self.warning_messages.append(message)


def _patch_route_dependencies(monkeypatch, *, backing_result=None, backing_error=None):
    monkeypatch.setattr(compact_module, "_require_loopback", lambda request: None)
    monkeypatch.setattr(compact_module, "web_mode_enabled", lambda: True)
    monkeypatch.setattr(compact_module, "prepare_and_verify_codex_web_mode", lambda reasoning: None)
    monkeypatch.setattr(compact_module, "install_codex_chatgpt_network_tuning", lambda: None)
    monkeypatch.setattr(
        compact_module,
        "_responses_request_to_chat_request",
        lambda body, stream=False: SimpleNamespace(messages=[]),
    )
    monkeypatch.setattr(compact_module, "_sanitize_codex_tool_payload", lambda payload: payload)
    monkeypatch.setattr(
        compact_module,
        "_sanitize_codex_root_workdirs",
        lambda payload, messages: payload,
    )

    async def _run_chat_completion_final(**kwargs):
        if backing_error is not None:
            raise backing_error
        return backing_result

    monkeypatch.setattr(
        compact_module,
        "_run_chat_completion_final",
        _run_chat_completion_final,
    )


def test_compact_route_is_registered():
    assert "/v1/responses/compact" in {route.path for route in router.routes}


def test_compact_request_disables_tools_and_does_not_pin_a_new_model():
    body = CodexCompactRequest(
        model="incoming-codex-model",
        input=_history(),
        instructions="Important project rule.",
        tools=[{"type": "function", "name": "exec_command", "parameters": {}}],
        parallel_tool_calls=True,
        reasoning={"effort": "high"},
    )

    adapted = compact_request_to_responses(body)

    assert adapted.model == "incoming-codex-model"
    assert adapted.input == body.input
    assert adapted.stream is False
    assert adapted.store is False
    assert adapted.tools is None
    assert adapted.tool_choice == "none"
    assert adapted.parallel_tool_calls is False
    assert adapted.reasoning == {"effort": "high"}
    assert "Important project rule." in (adapted.instructions or "")
    assert "Do not call tools" in (adapted.instructions or "")


def test_compact_output_returns_only_assistant_message_items():
    adapted = compact_request_to_responses(
        CodexCompactRequest(model="chatgpt", input=_history())
    )
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Goal: continue ALPHA. Tests were green.",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {},
    }

    output = compact_output_items(adapted, payload)

    assert len(output) == 1
    assert output[0]["type"] == "message"
    assert output[0]["role"] == "assistant"
    content = output[0].get("content") or []
    assert any("ALPHA" in str(part.get("text") or "") for part in content if isinstance(part, dict))


def test_compact_output_rejects_function_call_only_payload():
    adapted = compact_request_to_responses(
        CodexCompactRequest(model="chatgpt", input=_history())
    )
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "exec_command", "arguments": "{}"},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {},
    }

    assert compact_output_items(adapted, payload) == []


def test_compact_route_success_is_compatible_with_single_argument_secure_logger(monkeypatch):
    logger = _SingleArgumentLogger()
    monkeypatch.setattr(compact_module, "logger", logger)
    _patch_route_dependencies(
        monkeypatch,
        backing_result=(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Preserve ALPHA-42 and continue compact protocol verification.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {},
            },
        ),
    )

    result = asyncio.run(
        compact_module.codex_responses_compact(
            object(),
            CodexCompactRequest(model="chatgpt", input=_history()),
            authenticated=False,
        )
    )

    assert isinstance(result, dict)
    output = result.get("output")
    assert isinstance(output, list) and len(output) == 1
    assert logger.info_messages == ["[CODEX_COMPACT] compacted history into 1 assistant item(s)"]


def test_compact_route_backing_failure_logs_with_single_argument_secure_logger(monkeypatch):
    logger = _SingleArgumentLogger()
    monkeypatch.setattr(compact_module, "logger", logger)
    _patch_route_dependencies(monkeypatch, backing_error=RuntimeError("boom"))

    response = asyncio.run(
        compact_module.codex_responses_compact(
            object(),
            CodexCompactRequest(model="chatgpt", input=_history()),
            authenticated=False,
        )
    )

    assert response.status_code == 502
    body = json.loads(response.body)
    assert body["error"]["code"] == "responses_compact_backing_failed"
    assert logger.warning_messages == ["Codex compact backing request failed: boom"]
