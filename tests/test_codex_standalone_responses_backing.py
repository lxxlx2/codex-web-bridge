from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.responses import JSONResponse, StreamingResponse

from app.api import codex_runtime
from app.api import standalone_responses_backing as backing


class StandaloneResponsesBackingTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _payload(*, text: str = "done", finish_reason: str = "stop"):
        return {
            "choices": [
                {
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        }

    async def test_nonstream_success_uses_extracted_executor_and_stores_state(self) -> None:
        body = codex_runtime.ResponsesRequest(
            model="chatgpt",
            input="hello",
            stream=False,
        )
        payload = self._payload()
        store = MagicMock()

        with (
            patch.object(
                backing,
                "execute_chatgpt_nonstream",
                new=AsyncMock(return_value=(200, payload)),
            ) as execute,
            patch.object(backing, "_store_responses_state", new=store),
        ):
            response = await backing.create_response(
                request=SimpleNamespace(),
                body=body,
                authenticated=True,
            )

        self.assertIsInstance(response, JSONResponse)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["output"][0]["content"][0]["text"], "done")
        execute.assert_awaited_once()
        store.assert_called_once()
        self.assertTrue(str(store.call_args.args[0]).startswith("resp_"))
        self.assertTrue(store.call_args.kwargs["enabled"])

    async def test_nonstream_error_preserves_status_and_does_not_store_state(self) -> None:
        body = codex_runtime.ResponsesRequest(
            model="chatgpt",
            input="hello",
            stream=False,
        )
        payload = {
            "error": {
                "message": "backing unavailable",
                "type": "execution_error",
                "code": "backing_unavailable",
            }
        }
        store = MagicMock()

        with (
            patch.object(
                backing,
                "execute_chatgpt_nonstream",
                new=AsyncMock(return_value=(503, payload)),
            ),
            patch.object(backing, "_store_responses_state", new=store),
        ):
            response = await backing.create_response(
                request=SimpleNamespace(),
                body=body,
                authenticated=True,
            )

        self.assertIsInstance(response, JSONResponse)
        self.assertEqual(response.status_code, 503)
        data = json.loads(response.body.decode("utf-8"))
        self.assertEqual(data["status"], "failed")
        self.assertEqual(data["error"]["code"], "backing_unavailable")
        store.assert_not_called()

    async def test_stream_uses_extracted_executor_and_emits_terminal_responses_events(self) -> None:
        body = codex_runtime.ResponsesRequest(
            model="chatgpt",
            input="hello",
            stream=True,
        )
        payload = self._payload()
        store = MagicMock()

        with (
            patch.object(
                backing,
                "execute_chatgpt_nonstream",
                new=AsyncMock(return_value=(200, payload)),
            ) as execute,
            patch.object(backing, "_store_responses_state", new=store),
        ):
            response = await backing.create_response(
                request=SimpleNamespace(),
                body=body,
                authenticated=True,
            )
            self.assertIsInstance(response, StreamingResponse)
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk))

        wire = "".join(chunks)
        self.assertIn("event: response.created", wire)
        self.assertIn("event: response.output_item.done", wire)
        self.assertIn("event: response.completed", wire)
        self.assertIn('"text": "done"', wire)
        execute.assert_awaited_once()
        store.assert_called_once()


if __name__ == "__main__":
    unittest.main()
