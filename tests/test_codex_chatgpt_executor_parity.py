from __future__ import annotations

import json
import unittest

from app.services import codex_chatgpt_executor as executor


class CodexChatGPTExecutorParityTests(unittest.TestCase):
    """Frozen formatting/error contracts from the validated integrated baseline."""

    def test_json_object_prompt_matches_frozen_contract(self) -> None:
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "return data"},
        ]
        response_format = {"type": "json_object"}
        expected_hint = (
            "\n\n[系统指令：请以 JSON 格式输出你的回复。确保输出是有效的 JSON 对象，"
            "不要包含 ```json 代码块标记或任何其他非 JSON 文字。]"
        )

        actual = executor._apply_response_format(messages, response_format)

        self.assertEqual(
            actual,
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "return data" + expected_hint},
            ],
        )
        self.assertEqual(messages[-1]["content"], "return data")

    def test_json_schema_prompt_matches_frozen_contract(self) -> None:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "return object"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.invalid/a.png"},
                    },
                ],
            }
        ]
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        }
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "result",
                "schema": schema,
                "strict": True,
            },
        }
        expected_hint = (
            "\n\n[系统指令：请严格按照以下 JSON Schema 格式输出你的回复，确保输出是有效的 JSON，"
            "不要包含代码块标记：\n"
            + json.dumps(schema, ensure_ascii=False, indent=2)
            + "]"
        )

        actual = executor._apply_response_format(messages, response_format)

        self.assertEqual(actual[0]["content"][0]["text"], "return object" + expected_hint)
        self.assertEqual(
            actual[0]["content"][1],
            {"type": "image_url", "image_url": {"url": "https://example.invalid/a.png"}},
        )
        self.assertEqual(messages[0]["content"][0]["text"], "return object")

    def test_text_format_is_identity(self) -> None:
        messages = [{"role": "user", "content": "plain"}]
        self.assertIs(executor._apply_response_format(messages, {"type": "text"}), messages)

    def test_browser_error_preserves_structured_status_and_code(self) -> None:
        error = executor._browser_payload_error(
            {
                "error": {
                    "message": "blocked",
                    "type": "execution_error",
                    "code": "policy_blocked",
                    "status_code": 422,
                }
            }
        )
        self.assertIsNotNone(error)
        self.assertEqual(error.code, "policy_blocked")
        self.assertEqual(error.status_code, 422)
        self.assertEqual(str(error), "blocked")


if __name__ == "__main__":
    unittest.main()
