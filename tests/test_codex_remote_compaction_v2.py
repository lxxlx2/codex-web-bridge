import asyncio
import json
from types import SimpleNamespace

import pytest

from app.api.chat import ResponsesRequest
from app.services import codex_remote_compaction_v2 as remote


def _message(role: str, text: str):
    content_type = "input_text" if role in {"user", "developer", "system"} else "output_text"
    return {
        "type": "message",
        "role": role,
        "content": [{"type": content_type, "text": text}],
    }


def _trigger_body(*, input_items=None, tools=None):
    return ResponsesRequest(
        model="chatgpt",
        stream=True,
        input=input_items
        or [
            _message("user", "Keep project ALPHA and continue."),
            {"type": "compaction_trigger"},
        ],
        tools=tools
        or [
            {
                "type": "function",
                "name": "exec_command",
                "description": "test tool",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        tool_choice="auto",
        parallel_tool_calls=True,
        instructions="Preserve the active project constraints.",
        reasoning={"effort": "high"},
    )


def test_envelope_round_trip_preserves_unicode():
    summary = "目标：继续 ALPHA-42。路径 docs/状态.md。测试 ✅。"
    envelope = remote.encode_compaction_envelope(summary)

    assert envelope.startswith("uwa-codex-compact-v1.")
    assert summary not in envelope
    assert remote.decode_compaction_envelope(envelope) == summary


def test_envelope_rejects_foreign_and_corrupt_payloads():
    with pytest.raises(remote.RemoteCompactionV2ProtocolError, match="foreign"):
        remote.decode_compaction_envelope("not-uwa-data")

    envelope = remote.encode_compaction_envelope("preserve state")
    encoded, digest = envelope.rsplit(".", 1)
    replacement = "0" if digest[-1] != "0" else "1"
    corrupt = encoded + "." + digest[:-1] + replacement
    with pytest.raises(remote.RemoteCompactionV2ProtocolError, match="integrity"):
        remote.decode_compaction_envelope(corrupt)


def test_envelope_rejects_oversized_summary():
    with pytest.raises(remote.RemoteCompactionV2ProtocolError, match="exceeds"):
        remote.encode_compaction_envelope("x" * (remote._MAX_SUMMARY_BYTES + 1))


def test_trigger_requires_exactly_one_trailing_control_item():
    assert remote.has_remote_compaction_trigger(
        [_message("user", "state"), {"type": "compaction_trigger"}]
    )

    bad_cases = [
        [{"type": "compaction_trigger"}, _message("user", "late")],
        [
            _message("user", "state"),
            {"type": "compaction_trigger"},
            {"type": "compaction_trigger"},
        ],
        [_message("user", "state"), {"type": "compaction_trigger", "id": "bad"}],
        [{"type": "compaction_trigger"}],
    ]
    for source in bad_cases:
        with pytest.raises(remote.RemoteCompactionV2ProtocolError):
            remote.has_remote_compaction_trigger(source)


def test_rewrite_compaction_history_exposes_only_summary_context():
    summary = "Continue from the compact checkpoint."
    envelope = remote.encode_compaction_envelope(summary)
    source = [
        _message("system", "base"),
        {"type": "compaction", "encrypted_content": envelope},
        _message("user", "next"),
    ]

    rewritten = remote.rewrite_uwa_compaction_history(source)

    assert rewritten[0] == source[0]
    assert rewritten[2] == source[2]
    compacted = rewritten[1]
    assert compacted["type"] == "message"
    assert compacted["role"] == "assistant"
    text = compacted["content"][0]["text"]
    assert summary in text
    assert envelope not in json.dumps(rewritten, ensure_ascii=False)


def test_rewrite_compaction_history_fails_closed_on_foreign_or_multiple_items():
    with pytest.raises(remote.RemoteCompactionV2ProtocolError, match="foreign"):
        remote.rewrite_uwa_compaction_history(
            [{"type": "compaction", "encrypted_content": "foreign"}]
        )

    envelope = remote.encode_compaction_envelope("summary")
    with pytest.raises(remote.RemoteCompactionV2ProtocolError, match="multiple"):
        remote.rewrite_uwa_compaction_history(
            [
                {"type": "compaction", "encrypted_content": envelope},
                {"type": "compaction", "encrypted_content": envelope},
            ]
        )

    with pytest.raises(remote.RemoteCompactionV2ProtocolError, match="unsupported"):
        remote.rewrite_uwa_compaction_history(
            [{"type": "context_compaction", "encrypted_content": envelope}]
        )


def test_build_backing_body_strips_trigger_tools_and_previous_state():
    older_summary = remote.encode_compaction_envelope("Earlier compact state.")
    body = _trigger_body(
        input_items=[
            _message("system", "base"),
            {"type": "compaction", "encrypted_content": older_summary},
            _message("user", "latest"),
            {"type": "compaction_trigger"},
        ]
    )
    body.previous_response_id = "resp_should_not_be_replayed"

    backing = remote.build_compaction_backing_body(body)

    assert backing.previous_response_id is None
    assert backing.tools is None
    assert backing.tool_choice == "none"
    assert backing.parallel_tool_calls is False
    assert backing.stream is False
    assert backing.store is False
    assert all(item.get("type") != "compaction_trigger" for item in backing.input)
    assert all(item.get("type") != "compaction" for item in backing.input)
    assert any(
        "Earlier compact state." in json.dumps(item, ensure_ascii=False)
        for item in backing.input
    )
    assert "Do not call tools" in backing.instructions
    assert "Preserve the active project constraints." in backing.instructions


def test_extract_backing_summary_rejects_tool_call():
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": "call_1"}],
                }
            }
        ]
    }
    with pytest.raises(remote.RemoteCompactionV2ProtocolError, match="tool call"):
        remote.extract_backing_summary(payload)


def test_compaction_usage_is_non_zero():
    body = remote.build_compaction_backing_body(_trigger_body())
    usage = remote.compaction_usage(body, "compact summary")

    assert usage["input_tokens"] > 0
    assert usage["output_tokens"] > 0
    assert usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]


class _Request:
    async def is_disconnected(self):
        return False


def _fake_v2(backing_capture):
    counter = {"value": 0}

    def new_response_id():
        counter["value"] += 1
        return f"resp_test_{counter['value']}"

    def build_response(body, chat_payload, *, response_id, created_at, status, error, **kwargs):
        return {
            "id": response_id,
            "object": "response",
            "created_at": created_at,
            "model": body.model,
            "status": status,
            "output": [],
            "usage": chat_payload.get("usage", {}),
            "error": error,
        }

    def event(name, *, sequence_number, **fields):
        payload = {"type": name, "sequence_number": sequence_number, **fields}
        return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def to_chat(body, stream=False):
        backing_capture["body"] = body
        return SimpleNamespace(
            messages=body.input,
            tools=body.tools,
            tool_choice=body.tool_choice,
        )

    async def run_chat_completion_final(**kwargs):
        chat = kwargs["body"]
        assert chat.tools is None
        assert chat.tool_choice == "none"
        assert all(item.get("type") != "compaction_trigger" for item in chat.messages)
        return (
            200,
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Preserve ALPHA and continue the pending repair.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {},
            },
        )

    return SimpleNamespace(
        _new_response_id=new_response_id,
        _build_responses_object=build_response,
        _codex_event=event,
        _responses_request_to_chat_request=to_chat,
        _run_chat_completion_final=run_chat_completion_final,
        _CODEX_SSE_KEEPALIVE_SEC=0.01,
        prepare_and_verify_codex_web_mode=lambda reasoning: {"verified": True},
        install_codex_chatgpt_network_tuning=lambda: None,
    )


def test_remote_stream_emits_exactly_one_compaction_and_completed():
    capture = {}
    fake = _fake_v2(capture)

    async def collect():
        chunks = []
        async for chunk in remote._stream_remote_compaction_v2(
            v2=fake,
            request=_Request(),
            body=_trigger_body(),
            authenticated=False,
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(collect())
    text = "".join(chunks)
    blocks = [block for block in text.split("\n\n") if "data:" in block]
    payloads = [
        json.loads("\n".join(line[5:].lstrip() for line in block.splitlines() if line.startswith("data:")))
        for block in blocks
    ]

    output_items = [payload["item"] for payload in payloads if payload["type"] == "response.output_item.done"]
    completed = [payload for payload in payloads if payload["type"] == "response.completed"]

    assert len(output_items) == 1
    assert output_items[0]["type"] == "compaction"
    assert remote.decode_compaction_envelope(output_items[0]["encrypted_content"]) == (
        "Preserve ALPHA and continue the pending repair."
    )
    assert len(completed) == 1
    response = completed[0]["response"]
    assert response["status"] == "completed"
    assert len(response["output"]) == 1
    assert response["output"][0]["type"] == "compaction"
    assert response["usage"]["total_tokens"] > 0
    assert capture["body"].tools is None
