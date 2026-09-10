#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api import codex_responses_v2 as mod


class FakeRequest:
    async def is_disconnected(self) -> bool:
        return False


class StreamCancellationTests(unittest.IsolatedAsyncioTestCase):
    def stream_patches(self, worker, reuse_calls, *, heartbeat_sec: float):
        stack = ExitStack()
        stack.enter_context(patch.object(mod, "_run_chat_completion_final", worker))
        stack.enter_context(
            patch.object(
                mod,
                "_responses_request_to_chat_request",
                lambda body, stream=False: SimpleNamespace(messages=[]),
            )
        )
        stack.enter_context(
            patch.object(
                mod,
                "_build_responses_object",
                lambda *args, **kwargs: {
                    "output": [],
                    "status": kwargs.get("status"),
                },
            )
        )
        stack.enter_context(
            patch.object(
                mod,
                "set_codex_workflow_reuse_hint",
                lambda value: reuse_calls.append(value),
            )
        )
        stack.enter_context(patch.object(mod, "_sanitize_codex_tool_payload", lambda payload: payload))
        stack.enter_context(
            patch.object(
                mod,
                "_sanitize_codex_root_workdirs",
                lambda payload, messages: payload,
            )
        )
        stack.enter_context(
            patch.object(
                mod,
                "_responses_completion_status_from_chat_payload",
                lambda payload: ("completed", None, "response.completed"),
            )
        )
        stack.enter_context(patch.object(mod, "_codex_wire_item", lambda item: item))
        stack.enter_context(patch.object(mod, "_store_responses_state", lambda *args, **kwargs: None))
        stack.enter_context(patch.object(mod, "_persist_codex_history", lambda *args, **kwargs: None))
        stack.enter_context(patch.object(mod, "current_chatgpt_conversation_path", lambda: ""))
        stack.enter_context(patch.object(mod, "bind_response_to_conversation", lambda *args, **kwargs: None))
        stack.enter_context(patch.object(mod, "target_web_model", lambda: "chatgpt"))
        stack.enter_context(patch.object(mod, "_CODEX_SSE_KEEPALIVE_SEC", heartbeat_sec))
        return stack

    def make_stream(self):
        body = SimpleNamespace(store=True)
        return dict(
            request=FakeRequest(),
            state_body=body,
            browser_source_body=body,
            reuse_web_conversation=False,
            reused_path="",
            reasoning="high",
            authenticated=True,
        )

    async def test_consumer_cancellation_cleans_backing_task_and_propagates(self):
        started = asyncio.Event()
        cancelled = asyncio.Event()
        reuse_calls = []

        async def worker(**kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        with self.stream_patches(worker, reuse_calls, heartbeat_sec=10.0):
            stream = mod._stream_codex_v2_attempt(**self.make_stream())
            await stream.__anext__()
            pending = asyncio.create_task(stream.__anext__())
            await asyncio.wait_for(started.wait(), 1.0)
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
            await asyncio.wait_for(cancelled.wait(), 1.0)
            self.assertTrue(cancelled.is_set())
            self.assertEqual(reuse_calls[-1], False)

    async def test_aclose_cleans_backing_task_after_progress_event(self):
        started = asyncio.Event()
        cancelled = asyncio.Event()
        reuse_calls = []

        async def worker(**kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        with self.stream_patches(worker, reuse_calls, heartbeat_sec=0.01):
            stream = mod._stream_codex_v2_attempt(**self.make_stream())
            await stream.__anext__()
            progress = await stream.__anext__()
            self.assertIsInstance(progress, str)
            self.assertTrue(progress)
            await asyncio.wait_for(started.wait(), 1.0)
            await stream.aclose()
            await asyncio.wait_for(cancelled.wait(), 1.0)
            self.assertTrue(cancelled.is_set())
            self.assertEqual(reuse_calls[-1], False)

    async def test_normal_completion_does_not_cancel_finished_worker(self):
        completed = asyncio.Event()
        cancelled = asyncio.Event()
        reuse_calls = []

        async def worker(**kwargs):
            try:
                completed.set()
                return 200, {"choices": [], "usage": {}}
            except asyncio.CancelledError:
                cancelled.set()
                raise

        with self.stream_patches(worker, reuse_calls, heartbeat_sec=10.0):
            stream = mod._stream_codex_v2_attempt(**self.make_stream())
            events = [event async for event in stream]
            self.assertTrue(completed.is_set())
            self.assertFalse(cancelled.is_set())
            self.assertTrue(any("response.completed" in event for event in events))
            self.assertEqual(reuse_calls[-1], False)


if __name__ == "__main__":
    unittest.main()
