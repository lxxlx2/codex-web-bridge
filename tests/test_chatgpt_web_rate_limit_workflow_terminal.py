from __future__ import annotations

from app.core.browser.workflow import BrowserWorkflowMixin
from app.core.config import SSEFormatter


def _terminal_chunk(detail: str) -> str:
    return SSEFormatter().pack_error(f"stream_terminal_error:{detail}")


def test_chatgpt_rate_limit_terminal_chunk_is_not_retried():
    chunk = _terminal_chunk(
        "429 Too Many Requests: chatgpt_web_rate_limited"
    )

    assert BrowserWorkflowMixin._is_stream_terminal_error_chunk(chunk) is True
    assert BrowserWorkflowMixin._is_retriable_stream_terminal_error_chunk(chunk) is False
    assert BrowserWorkflowMixin._get_stream_terminal_error_detail(chunk) == (
        "429 Too Many Requests: chatgpt_web_rate_limited"
    )


def test_ambiguous_submit_terminal_chunk_is_not_retried():
    chunk = _terminal_chunk(
        "422 Unprocessable Entity: chatgpt_send_submission_unknown"
    )

    assert BrowserWorkflowMixin._is_stream_terminal_error_chunk(chunk) is True
    assert BrowserWorkflowMixin._is_retriable_stream_terminal_error_chunk(chunk) is False
    assert BrowserWorkflowMixin._get_stream_terminal_error_detail(chunk) == (
        "422 Unprocessable Entity: chatgpt_send_submission_unknown"
    )

def test_preexisting_generation_send_block_is_terminal():
    assert BrowserWorkflowMixin._is_terminal_step_workflow_error(
        "send_blocked_by_preexisting_generation"
    ) is True


def test_undispatched_send_action_is_terminal():
    assert BrowserWorkflowMixin._is_terminal_step_workflow_error(
        "send_action_not_dispatched"
    ) is True


def test_unrelated_workflow_error_is_not_promoted_to_terminal_send_failure():
    assert BrowserWorkflowMixin._is_terminal_step_workflow_error(
        "some_other_workflow_error"
    ) is False
