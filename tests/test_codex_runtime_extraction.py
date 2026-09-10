from __future__ import annotations

import unittest

from fastapi import HTTPException

from app.api import legacy_chat_runtime as legacy
from app.api import codex_runtime as runtime


class CodexRuntimeExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        runtime._responses_state_by_id.clear()
        legacy._responses_state_by_id.clear()

    def test_request_model_accepts_codex_extra_fields(self) -> None:
        body = runtime.ResponsesRequest(
            model="chatgpt",
            input="hello",
            stream=True,
            reasoning={"effort": "high"},
            unknown_codex_field={"kept": True},
        )
        dumped = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        self.assertEqual(dumped["unknown_codex_field"], {"kept": True})

    def test_request_to_chat_matches_legacy_for_tool_roundtrip(self) -> None:
        payload = {
            "model": "chatgpt",
            "instructions": "system rule",
            "input": [
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "inspect"}]},
                {"type": "function_call", "call_id": "call_1", "name": "exec_command", "arguments": {"cmd": "pwd"}},
                {"type": "function_call_output", "call_id": "call_1", "output": "workspace"},
            ],
            "tools": [
                {
                    "type": "function",
                    "name": "exec_command",
                    "description": "run command",
                    "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
                }
            ],
            "tool_choice": {"type": "function", "name": "exec_command"},
            "parallel_tool_calls": False,
            "reasoning": {"effort": "high"},
        }
        extracted = runtime._responses_request_to_chat_request(
            runtime.ResponsesRequest(**payload), stream=False
        )
        baseline = legacy._responses_request_to_chat_request(
            legacy.ResponsesRequest(**payload), stream=False
        )
        extracted_data = extracted.model_dump() if hasattr(extracted, "model_dump") else extracted.dict()
        baseline_data = baseline.model_dump() if hasattr(baseline, "model_dump") else baseline.dict()
        self.assertEqual(extracted_data, baseline_data)

    def test_response_object_matches_legacy_protocol_shape(self) -> None:
        body_payload = {
            "model": "chatgpt",
            "input": "hello",
            "stream": True,
            "tools": [{"type": "function", "name": "exec_command", "parameters": {"type": "object"}}],
            "reasoning": {"effort": "high"},
            "metadata": {"purpose": "parity"},
        }
        chat_payload = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_abc",
                                "type": "function",
                                "function": {"name": "exec_command", "arguments": "{\"cmd\":\"pwd\"}"},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        }
        extracted = runtime._build_responses_object(
            runtime.ResponsesRequest(**body_payload),
            chat_payload,
            response_id="resp_fixed",
            created_at=123,
        )
        baseline = legacy._build_responses_object(
            legacy.ResponsesRequest(**body_payload),
            chat_payload,
            response_id="resp_fixed",
            created_at=123,
        )
        extracted.pop("completed_at", None)
        baseline.pop("completed_at", None)
        self.assertEqual(extracted, baseline)

    def test_state_store_and_load_are_self_contained(self) -> None:
        payload = {
            "choices": [
                {"message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}
            ]
        }
        runtime._store_responses_state(
            "resp_state",
            [{"role": "user", "content": "go"}],
            payload,
            enabled=True,
        )
        self.assertEqual(
            runtime._load_responses_state("resp_state"),
            [
                {"role": "user", "content": "go"},
                {"role": "assistant", "content": "done"},
            ],
        )
        with self.assertRaises(HTTPException):
            legacy._load_responses_state("resp_state")

    def test_completion_and_error_helpers_match_legacy(self) -> None:
        for payload in (
            {"choices": [{"finish_reason": "stop"}]},
            {"choices": [{"finish_reason": "length"}]},
            {"choices": [{"finish_reason": "content_filter"}]},
        ):
            self.assertEqual(
                runtime._responses_completion_status_from_chat_payload(payload),
                legacy._responses_completion_status_from_chat_payload(payload),
            )
        error_payload = {"error": {"message": "boom", "type": "execution_error"}}
        self.assertEqual(
            runtime._responses_error_payload(error_payload),
            legacy._responses_error_payload(error_payload),
        )


if __name__ == "__main__":
    unittest.main()
