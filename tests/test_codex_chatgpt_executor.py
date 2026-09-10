from __future__ import annotations

import asyncio
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import main
from app.api import codex_compact, codex_responses_v2, codex_runtime
from app.services import codex_chatgpt_executor as executor
from app.services.request_manager import RequestContext, RequestStatus


class _FakeBrowser:
    def __init__(self, payload=None) -> None:
        self.payload = payload or {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "done"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        }
        self.calls = []

    def execute_workflow_for_route_domain(self, route_domain, messages, **kwargs):
        self.calls.append(
            {
                "route_domain": route_domain,
                "messages": messages,
                "kwargs": kwargs,
            }
        )
        yield json.dumps(self.payload)


async def _sleep_until_cancelled(*args, **kwargs):
    del args, kwargs
    await asyncio.Event().wait()


async def _run_worker_inline(worker_fn, **kwargs):
    del kwargs
    return worker_fn()


class CodexChatGPTExecutorTests(unittest.IsolatedAsyncioTestCase):
    def test_standalone_modules_bind_extracted_executor_without_legacy_runtime(self) -> None:
        self.assertIs(codex_runtime._run_chat_completion_final, executor.execute_chatgpt_nonstream)
        self.assertIs(codex_compact._run_chat_completion_final, executor.execute_chatgpt_nonstream)
        self.assertIs(codex_responses_v2._run_chat_completion_final, executor.execute_chatgpt_nonstream)
        self.assertNotIn("app.api.legacy_chat_runtime", sys.modules)
        self.assertTrue(any(getattr(route, "path", "") == "/v1/responses" for route in main.app.routes))

    def test_browser_round_is_pinned_to_chatgpt_route(self) -> None:
        browser = _FakeBrowser()
        payload = executor._execute_browser_non_stream_messages(
            browser,
            [{"role": "user", "content": "hello"}],
            "req_route",
            stop_checker=lambda: False,
            requested_model="chatgpt",
        )

        self.assertEqual(payload["choices"][0]["message"]["content"], "done")
        self.assertEqual(len(browser.calls), 1)
        call = browser.calls[0]
        self.assertEqual(call["route_domain"], "chatgpt.com")
        self.assertFalse(call["kwargs"]["stream"])
        self.assertEqual(call["kwargs"]["task_id"], "req_route")
        self.assertEqual(call["kwargs"]["requested_model"], "chatgpt")

    async def test_normal_execution_finishes_request_lifecycle(self) -> None:
        ctx = RequestContext("req_normal")
        browser = _FakeBrowser()
        finish_request = MagicMock()
        capture_payload = MagicMock()
        body = codex_runtime.ChatRequest(
            model="chatgpt",
            messages=[{"role": "user", "content": "hello"}],
            stream=False,
        )

        with (
            patch.object(executor.cancel_storm_guard, "get_client_fingerprint", return_value="test-client"),
            patch.object(executor.cancel_storm_guard, "maybe_backoff", new=AsyncMock(return_value=0.0)),
            patch.object(executor.request_manager, "create_request", return_value=ctx),
            patch.object(executor.request_manager, "record_request_input", new=MagicMock()),
            patch.object(executor.request_manager, "start_request", side_effect=lambda item: item.mark_running()),
            patch.object(executor.request_manager, "capture_response_payload", new=capture_payload),
            patch.object(executor.request_manager, "capture_error", new=MagicMock()),
            patch.object(executor.request_manager, "finish_request", new=finish_request),
            patch.object(executor, "watch_client_disconnect", new=_sleep_until_cancelled),
            patch.object(executor, "get_browser", return_value=browser),
            patch.object(executor, "_run_tracked_round", new=_run_worker_inline),
            patch.object(executor, "has_tool_calling_request", return_value=False),
        ):
            status_code, payload = await executor.execute_chatgpt_nonstream(
                request=SimpleNamespace(),
                body=body,
                authenticated=True,
            )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["choices"][0]["message"]["content"], "done")
        self.assertEqual(ctx.status, RequestStatus.COMPLETED)
        capture_payload.assert_called_once_with(ctx, payload)
        finish_request.assert_called_once_with(ctx, success=True)
        self.assertEqual(browser.calls[0]["route_domain"], executor.CHATGPT_ROUTE_DOMAIN)

    async def test_caller_cancellation_propagates_and_finishes_lifecycle(self) -> None:
        ctx = RequestContext("req_cancel")
        finish_request = MagicMock()
        body = codex_runtime.ChatRequest(
            model="chatgpt",
            messages=[{"role": "user", "content": "hello"}],
            stream=False,
        )

        async def _cancel_worker(worker_fn, **kwargs):
            del worker_fn, kwargs
            raise asyncio.CancelledError()

        with (
            patch.object(executor.cancel_storm_guard, "get_client_fingerprint", return_value="test-client"),
            patch.object(executor.cancel_storm_guard, "maybe_backoff", new=AsyncMock(return_value=0.0)),
            patch.object(executor.request_manager, "create_request", return_value=ctx),
            patch.object(executor.request_manager, "record_request_input", new=MagicMock()),
            patch.object(executor.request_manager, "start_request", side_effect=lambda item: item.mark_running()),
            patch.object(executor.request_manager, "capture_response_payload", new=MagicMock()),
            patch.object(executor.request_manager, "capture_error", new=MagicMock()),
            patch.object(executor.request_manager, "finish_request", new=finish_request),
            patch.object(executor, "watch_client_disconnect", new=_sleep_until_cancelled),
            patch.object(executor, "get_browser", return_value=_FakeBrowser()),
            patch.object(executor, "_run_tracked_round", new=_cancel_worker),
            patch.object(executor, "has_tool_calling_request", return_value=False),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await executor.execute_chatgpt_nonstream(
                    request=SimpleNamespace(),
                    body=body,
                    authenticated=True,
                )

        self.assertEqual(ctx.status, RequestStatus.CANCELLED)
        self.assertEqual(ctx.cancel_reason, "coroutine_cancelled")
        finish_request.assert_called_once_with(ctx, success=False)

    async def test_tool_calling_path_returns_model_function_call_for_client_execution(self) -> None:
        ctx = RequestContext("req_tool")
        finish_request = MagicMock()
        tool_payload = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_test",
                                "type": "function",
                                "function": {"name": "exec_command", "arguments": "{\"cmd\":\"pwd\"}"},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
        body = codex_runtime.ChatRequest(
            model="chatgpt",
            messages=[{"role": "user", "content": "inspect workspace"}],
            stream=False,
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "exec_command",
                        "description": "Run a client command",
                        "parameters": {"type": "object"},
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": "exec_command"}},
        )

        with (
            patch.object(executor.cancel_storm_guard, "get_client_fingerprint", return_value="test-client"),
            patch.object(executor.cancel_storm_guard, "maybe_backoff", new=AsyncMock(return_value=0.0)),
            patch.object(executor.request_manager, "create_request", return_value=ctx),
            patch.object(executor.request_manager, "record_request_input", new=MagicMock()),
            patch.object(executor.request_manager, "start_request", side_effect=lambda item: item.mark_running()),
            patch.object(executor.request_manager, "capture_response_payload", new=MagicMock()),
            patch.object(executor.request_manager, "capture_error", new=MagicMock()),
            patch.object(executor.request_manager, "finish_request", new=finish_request),
            patch.object(executor, "watch_client_disconnect", new=_sleep_until_cancelled),
            patch.object(executor, "get_browser", return_value=_FakeBrowser()),
            patch.object(executor, "has_tool_calling_request", return_value=True),
            patch.object(executor, "_run_tool_calling", new=AsyncMock(return_value=tool_payload)) as run_tools,
        ):
            status_code, payload = await executor.execute_chatgpt_nonstream(
                request=SimpleNamespace(),
                body=body,
                authenticated=True,
            )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(
            payload["choices"][0]["message"]["tool_calls"][0]["function"]["name"],
            "exec_command",
        )
        run_tools.assert_awaited_once()
        self.assertEqual(ctx.status, RequestStatus.COMPLETED)
        finish_request.assert_called_once_with(ctx, success=True)


if __name__ == "__main__":
    unittest.main()
