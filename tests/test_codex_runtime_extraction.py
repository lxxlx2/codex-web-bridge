from __future__ import annotations

import importlib
import json
import unittest

from fastapi import HTTPException

from app.api import codex_runtime as runtime


class CodexRuntimeExtractionTests(unittest.TestCase):
    """Golden protocol tests for the extracted standalone Responses runtime.

    These expectations were frozen from the validated integrated baseline before
    the legacy generic chat runtime was removed from the standalone tree.
    """

    def setUp(self) -> None:
        runtime._responses_state_by_id.clear()

    def tearDown(self) -> None:
        runtime._responses_state_by_id.clear()

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

    def test_request_to_chat_matches_frozen_tool_roundtrip_contract(self) -> None:
        payload = {
            "model": "chatgpt",
            "instructions": "system rule",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "inspect"}],
                },
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "exec_command",
                    "arguments": {"cmd": "pwd"},
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": "workspace",
                },
            ],
            "tools": [
                {
                    "type": "function",
                    "name": "exec_command",
                    "description": "run command",
                    "parameters": {
                        "type": "object",
                        "properties": {"cmd": {"type": "string"}},
                    },
                }
            ],
            "tool_choice": {"type": "function", "name": "exec_command"},
            "parallel_tool_calls": False,
            "reasoning": {"effort": "high"},
        }
        extracted = runtime._responses_request_to_chat_request(
            runtime.ResponsesRequest(**payload), stream=False
        )
        data = extracted.model_dump() if hasattr(extracted, "model_dump") else extracted.dict()

        self.assertEqual(
            data["messages"],
            [
                {"role": "system", "content": "system rule"},
                {"role": "user", "content": "inspect"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "exec_command",
                                "arguments": json.dumps({"cmd": "pwd"}, ensure_ascii=False),
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "content": "workspace",
                },
            ],
        )
        self.assertEqual(
            data["tools"],
            [
                {
                    "type": "function",
                    "function": {
                        "name": "exec_command",
                        "description": "run command",
                        "parameters": {
                            "type": "object",
                            "properties": {"cmd": {"type": "string"}},
                        },
                    },
                }
            ],
        )
        self.assertEqual(
            data["tool_choice"],
            {"type": "function", "function": {"name": "exec_command"}},
        )
        self.assertFalse(data["stream"])
        self.assertFalse(data["parallel_tool_calls"])

    def test_response_object_matches_frozen_protocol_shape(self) -> None:
        body = runtime.ResponsesRequest(
            model="chatgpt",
            input="hello",
            stream=True,
            tools=[
                {
                    "type": "function",
                    "name": "exec_command",
                    "parameters": {"type": "object"},
                }
            ],
            reasoning={"effort": "high"},
            metadata={"purpose": "parity"},
        )
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
                                "function": {
                                    "name": "exec_command",
                                    "arguments": "{\"cmd\":\"pwd\"}",
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 4,
                "total_tokens": 14,
            },
        }
        response = runtime._build_responses_object(
            body,
            chat_payload,
            response_id="resp_fixed",
            created_at=123,
        )
        response.pop("completed_at", None)

        self.assertEqual(response["id"], "resp_fixed")
        self.assertEqual(response["object"], "response")
        self.assertEqual(response["created_at"], 123)
        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["model"], "chatgpt")
        self.assertEqual(response["reasoning"], {"effort": "high"})
        self.assertEqual(response["metadata"], {"purpose": "parity"})
        self.assertEqual(
            response["usage"],
            {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
        )
        self.assertEqual(
            response["output"],
            [
                {
                    "id": "fc_abc",
                    "type": "function_call",
                    "status": "completed",
                    "call_id": "call_abc",
                    "name": "exec_command",
                    "arguments": "{\"cmd\":\"pwd\"}",
                }
            ],
        )

    def test_state_store_and_load_are_self_contained(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "done"},
                    "finish_reason": "stop",
                }
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
        runtime._responses_state_by_id.clear()
        with self.assertRaises(HTTPException):
            runtime._load_responses_state("resp_state")

    def test_completion_and_error_helpers_match_frozen_contract(self) -> None:
        self.assertEqual(
            runtime._responses_completion_status_from_chat_payload(
                {"choices": [{"finish_reason": "stop"}]}
            ),
            ("completed", None, "response.completed"),
        )
        self.assertEqual(
            runtime._responses_completion_status_from_chat_payload(
                {"choices": [{"finish_reason": "length"}]}
            ),
            ("incomplete", {"reason": "max_output_tokens"}, "response.incomplete"),
        )
        self.assertEqual(
            runtime._responses_completion_status_from_chat_payload(
                {"choices": [{"finish_reason": "content_filter"}]}
            ),
            ("incomplete", {"reason": "content_filter"}, "response.incomplete"),
        )
        self.assertEqual(
            runtime._responses_error_payload(
                {"error": {"message": "boom", "type": "execution_error"}}
            ),
            {
                "message": "boom",
                "type": "execution_error",
                "code": "responses_backing_request_failed",
            },
        )

    def test_legacy_generic_chat_runtime_is_absent(self) -> None:
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("app.api.legacy_chat_runtime")


if __name__ == "__main__":
    unittest.main()
