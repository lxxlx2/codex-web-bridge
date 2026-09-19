import json
import os

from app.api.chat import ResponsesRequest
from app.services.codex_wire_observability import (
    summarize_responses_request,
    summarize_responses_sse,
    write_trace_attempt,
)


def _request_with_secret_text():
    return ResponsesRequest(
        model="chatgpt",
        stream=True,
        reasoning={"effort": "high"},
        input=[
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "TOP_SECRET_MARKER must not enter metadata"}],
            }
        ],
        tools=[
            {
                "type": "function",
                "name": "exec_command",
                "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
            }
        ],
    )


def test_request_metadata_does_not_store_prompt_text():
    summary = summarize_responses_request(_request_with_secret_text(), "exec_command")
    encoded = json.dumps(summary, ensure_ascii=False)

    assert "TOP_SECRET_MARKER" not in encoded
    assert summary["tool_names"] == ["exec_command"]
    assert summary["required_tool"] == "exec_command"
    assert summary["input"]["item_count"] == 1
    assert summary["input"]["text_chars"] > 0


def test_sse_summary_distinguishes_plain_text_from_real_function_call():
    plain = [
        "event: response.output_item.done\n"
        "data: {\"type\":\"response.output_item.done\",\"item\":{\"type\":\"message\",\"role\":\"assistant\",\"content\":[{\"type\":\"output_text\",\"text\":\"/\"}]}}\n\n",
        "event: response.completed\n"
        "data: {\"type\":\"response.completed\",\"response\":{\"id\":\"resp_1\",\"status\":\"completed\",\"output\":[]}}\n\n",
    ]
    tool = [
        "event: response.output_item.done\n"
        "data: {\"type\":\"response.output_item.done\",\"item\":{\"type\":\"function_call\",\"call_id\":\"call_1\",\"name\":\"exec_command\",\"arguments\":\"{\\\"cmd\\\":\\\"pwd\\\",\\\"workdir\\\":\\\"/\\\"}\"}}\n\n",
        "event: response.completed\n"
        "data: {\"type\":\"response.completed\",\"response\":{\"id\":\"resp_2\",\"status\":\"completed\",\"output\":[]}}\n\n",
    ]

    plain_summary = summarize_responses_sse(plain)
    tool_summary = summarize_responses_sse(tool)

    assert plain_summary["function_call_names"] == []
    assert plain_summary["output_text_chars"] == 1
    assert tool_summary["function_call_names"] == ["exec_command"]
    assert tool_summary["function_calls"][0]["has_workdir"] is True
    assert tool_summary["function_calls"][0]["workdir_is_root"] is True
    assert "cmd" in tool_summary["function_calls"][0]["argument_keys"]


def test_metadata_trace_files_are_private_and_do_not_store_full_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("UWA_CODEX_WIRE_TRACE", "metadata")
    monkeypatch.setenv("UWA_CODEX_WIRE_TRACE_DIR", str(tmp_path))
    monkeypatch.setenv("UWA_CODEX_WIRE_TRACE_MAX_FILES", "40")

    body = _request_with_secret_text()
    request_summary = summarize_responses_request(body, "exec_command")
    response_summary = {
        "function_call_names": ["exec_command"],
        "required_tool_satisfied": True,
    }

    write_trace_attempt(
        trace_id="test-trace",
        attempt=1,
        request_summary=request_summary,
        response_summary=response_summary,
        full_request=body,
        raw_sse="TOP_SECRET_RESPONSE",
    )

    request_path = tmp_path / "test-trace-attempt01-request.json"
    response_path = tmp_path / "test-trace-attempt01-response.json"
    assert request_path.exists()
    assert response_path.exists()

    request_text = request_path.read_text()
    response_text = response_path.read_text()
    assert "TOP_SECRET_MARKER" not in request_text
    assert "TOP_SECRET_RESPONSE" not in response_text
    assert "full_request" not in request_text
    assert "raw_sse" not in response_text

    assert os.stat(request_path).st_mode & 0o777 == 0o600
    assert os.stat(response_path).st_mode & 0o777 == 0o600
