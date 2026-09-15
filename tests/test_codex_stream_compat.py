import json

from app.api.chat import ResponsesRequest
from app.services import codex_stream_compat as compat


def _completed_chunk(response_id: str, *, usage=None, output_text="done") -> str:
    payload = {
        "type": "response.completed",
        "sequence_number": 3,
        "response": {
            "id": response_id,
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": output_text,
                        }
                    ],
                }
            ],
            "usage": usage if usage is not None else {},
        },
    }
    return "event: response.completed\ndata: " + json.dumps(payload) + "\n\n"


def _payload(frame: str):
    data_line = next(line for line in frame.splitlines() if line.startswith("data: "))
    return json.loads(data_line[len("data: ") :])


def setup_function():
    with compat._USAGE_LOCK:
        compat._RESPONSE_TOTAL_TOKENS.clear()


def test_heartbeat_is_real_parseable_sse_event_not_comment():
    frame = compat.codex_heartbeat_event()
    assert frame.startswith("event: response.in_progress\n")
    assert not frame.lstrip().startswith(":")
    payload = _payload(frame)
    assert payload == {"type": "response.in_progress"}
    assert compat._is_codex_heartbeat(frame) is True


def test_zero_usage_is_replaced_with_conservative_nonzero_estimate():
    body = ResponsesRequest(
        model="chatgpt",
        input=[
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "x" * 1200}],
            }
        ],
    )
    frame = compat.inject_estimated_usage(
        _completed_chunk("resp_one", usage={}),
        state_body=body,
        source_body=body,
        responses_to_chat=None,
    )
    usage = _payload(frame)["response"]["usage"]
    assert usage["input_tokens"] > 0
    assert usage["output_tokens"] > 0
    assert usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]
    assert usage["input_tokens_details"]["cached_tokens"] == 0
    assert usage["output_tokens_details"]["reasoning_tokens"] == 0


def test_previous_response_estimate_grows_monotonically_for_continuation():
    first = ResponsesRequest(model="chatgpt", input="a" * 1200)
    first_frame = compat.inject_estimated_usage(
        _completed_chunk("resp_first", usage={}),
        state_body=first,
        source_body=first,
        responses_to_chat=None,
    )
    first_usage = _payload(first_frame)["response"]["usage"]

    second = ResponsesRequest(
        model="chatgpt",
        previous_response_id="resp_first",
        input="b" * 1200,
    )
    second_frame = compat.inject_estimated_usage(
        _completed_chunk("resp_second", usage={}),
        state_body=second,
        source_body=second,
        responses_to_chat=None,
    )
    second_usage = _payload(second_frame)["response"]["usage"]

    assert second_usage["input_tokens"] > first_usage["total_tokens"]
    assert second_usage["total_tokens"] > first_usage["total_tokens"]


def test_real_nonzero_usage_is_preserved_exactly():
    body = ResponsesRequest(model="chatgpt", input="hello")
    real_usage = {
        "input_tokens": 123,
        "input_tokens_details": {"cached_tokens": 20},
        "output_tokens": 45,
        "output_tokens_details": {"reasoning_tokens": 7},
        "total_tokens": 168,
    }
    original = _completed_chunk("resp_real", usage=real_usage)
    rewritten = compat.inject_estimated_usage(
        original,
        state_body=body,
        source_body=body,
        responses_to_chat=None,
    )
    assert rewritten == original
    assert compat._previous_total("resp_real") == 168


def test_non_terminal_events_are_not_rewritten():
    body = ResponsesRequest(model="chatgpt", input="hello")
    frame = 'event: response.created\ndata: {"type":"response.created"}\n\n'
    assert (
        compat.inject_estimated_usage(
            frame,
            state_body=body,
            source_body=body,
            responses_to_chat=None,
        )
        == frame
    )
