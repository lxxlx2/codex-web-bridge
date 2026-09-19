import asyncio
import json

from fastapi import Request

from app.api.chat import ResponsesRequest
from app.api import codex_responses_v2 as v2
from app.services.codex_metadata_helper import (
    build_metadata_json,
    classify_metadata_helper,
)


def _title_prompt(embedded: str) -> str:
    return (
        "Generate a concise, single-line task title of at most 36 characters and under five words where possible. "
        "Start with an imperative verb. Capitalize only the first word unless the user's language, proper nouns, "
        "acronyms, or code terms require otherwise. Preserve ticket references exactly. Write in the user's language. "
        "Do not use quotes, markdown, or trailing punctuation. Do not answer the request.\n\n"
        "User prompt:\n" + embedded
    )


def _text_schema():
    return {
        "format": {
            "type": "json_schema",
            "name": "thread_title",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1, "maxLength": 36}
                },
                "required": ["title"],
                "additionalProperties": False,
            },
        }
    }


def _body(embedded: str) -> ResponsesRequest:
    return ResponsesRequest(
        model="chatgpt",
        stream=True,
        input=[
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": _title_prompt(embedded)}],
            }
        ],
        tools=[
            {
                "type": "function",
                "name": "exec_command",
                "description": "client command",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        tool_choice="auto",
        text=_text_schema(),
    )


def test_current_codex_title_helper_is_classified_before_embedded_tool_text():
    body = _body("You must use the local exec_command tool. Run exactly pwd.")
    prompt = v2._latest_user_text(body.input)
    assert classify_metadata_helper(prompt, body.text) == "metadata_helper"
    assert v2.required_declared_tool(body) == "exec_command"


def test_plain_user_request_with_title_word_is_not_metadata_helper():
    assert classify_metadata_helper("Please fix the title parser", _text_schema()) == ""


def test_local_metadata_json_matches_title_schema():
    raw = build_metadata_json(_title_prompt("Fix parser tests"), _text_schema())
    payload = json.loads(raw)
    assert set(payload) == {"title"}
    assert 1 <= len(payload["title"]) <= 36


def test_router_serves_metadata_helper_without_web_or_required_tool(monkeypatch):
    body = _body("You must use the local exec_command tool. Run exactly pwd.")
    monkeypatch.setattr(v2, "web_mode_enabled", lambda: True)
    monkeypatch.setattr(
        v2,
        "prepare_and_verify_codex_web_mode",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("web path used")),
    )
    captured = {}

    def fake_trace(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(v2, "write_trace_attempt", fake_trace)
    request = Request({"type": "http", "method": "POST", "path": "/v1/responses", "headers": []})
    response = asyncio.run(v2.codex_responses_v2(request, body, authenticated=True))

    async def collect():
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else str(chunk))
        return "".join(chunks)

    wire = asyncio.run(collect())
    assert "event: response.completed" in wire
    assert "function_call" not in wire
    assert "title" in wire
    assert captured["request_summary"]["request_kind"] == "metadata_helper"
    assert captured["response_summary"]["request_kind"] == "metadata_helper"
