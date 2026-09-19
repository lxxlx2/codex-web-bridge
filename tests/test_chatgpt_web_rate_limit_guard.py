from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import WorkflowError
from app.services import chatgpt_web_rate_limit_guard as guard
from app.services.error_metadata import resolve_error_metadata


class _FakeTab:
    def __init__(self, url: str = "https://chatgpt.com/"):
        self.url = url


class _FakeExecutor:
    def __init__(self, *, cancelled: bool = False, url: str = "https://chatgpt.com/"):
        self.tab = _FakeTab(url)
        self.cancelled = cancelled

    def _check_cancelled(self):
        return self.cancelled


def _state_file(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "rate-limit.json"
    monkeypatch.setenv("UWA_CHATGPT_RATE_LIMIT_STATE", str(path))
    return path


def test_pre_submit_rate_limit_waits_then_allows_one_initial_send(tmp_path, monkeypatch):
    path = _state_file(tmp_path, monkeypatch)
    executor = _FakeExecutor()
    reasons = iter(["rate_limited", "none"])
    waits: list[str] = []

    monkeypatch.setattr(guard, "_surface_reason", lambda _executor: next(reasons))
    monkeypatch.setattr(
        guard,
        "_ack_rate_limit",
        lambda _executor: {"detected": True, "dismissed": True},
    )

    def fake_wait(_executor):
        waits.append("wait")
        return True

    monkeypatch.setattr(guard, "_wait_existing_cooldown", fake_wait)

    guard.guard_before_initial_send(executor)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["hits"] == 1
    assert data["backoff_seconds"] == 20.0
    assert data["blocked_until_epoch"] > data["last_seen_epoch"]
    assert waits == ["wait", "wait"]


def test_persistent_pre_submit_rate_limit_propagates_terminal_429(tmp_path, monkeypatch):
    path = _state_file(tmp_path, monkeypatch)
    executor = _FakeExecutor()
    reasons = iter(["rate_limited", "rate_limited"])
    monkeypatch.setattr(guard, "_surface_reason", lambda _executor: next(reasons))
    monkeypatch.setattr(
        guard,
        "_ack_rate_limit",
        lambda _executor: {"detected": True, "dismissed": False},
    )
    monkeypatch.setattr(guard, "_wait_existing_cooldown", lambda _executor: True)

    with pytest.raises(WorkflowError) as exc_info:
        guard.guard_before_initial_send(executor)

    text = str(exc_info.value)
    assert text == (
        "stream_terminal_error:429 Too Many Requests: "
        "chatgpt_web_rate_limited"
    )
    metadata = resolve_error_metadata(exc_info.value)
    assert metadata is not None
    assert metadata.code == "rate_limit_exceeded"
    assert metadata.status_code == 429
    assert metadata.retryable is False

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["hits"] == 1


def test_pre_submit_cancellation_unwinds_without_send(tmp_path, monkeypatch):
    _state_file(tmp_path, monkeypatch)
    executor = _FakeExecutor(cancelled=True)

    with pytest.raises(WorkflowError, match="request_cancelled"):
        guard.guard_before_initial_send(executor)


def test_backoff_escalates_and_caps(tmp_path, monkeypatch):
    _state_file(tmp_path, monkeypatch)

    first = guard._record_rate_limit(now=1000.0)
    second = guard._record_rate_limit(now=1001.0)
    third = guard._record_rate_limit(now=1002.0)
    fourth = guard._record_rate_limit(now=1003.0)

    assert first["backoff_seconds"] == 20.0
    assert second["backoff_seconds"] == 45.0
    assert third["backoff_seconds"] == 90.0
    assert fourth["backoff_seconds"] == 90.0
    assert fourth["blocked_until_epoch"] >= 1093.0


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("work_surface", "409 Conflict: chatgpt_web_work_surface"),
        ("work_quota_exhausted", "429 Too Many Requests: chatgpt_web_work_quota_exhausted"),
        ("usage_exhausted", "429 Too Many Requests: chatgpt_web_usage_exhausted"),
        ("auth_required", "503 Service Unavailable: chatgpt_web_auth_required"),
        ("challenge", "503 Service Unavailable: chatgpt_web_challenge"),
        ("unknown_surface", "503 Service Unavailable: chatgpt_web_surface_unknown"),
    ],
)
def test_surface_blockers_fail_closed_before_initial_send(tmp_path, monkeypatch, reason, expected):
    _state_file(tmp_path, monkeypatch)
    executor = _FakeExecutor()
    monkeypatch.setattr(guard, "_wait_existing_cooldown", lambda _executor: True)
    monkeypatch.setattr(guard, "_surface_reason", lambda _executor: reason)

    with pytest.raises(WorkflowError) as exc_info:
        guard.guard_before_initial_send(executor)

    assert str(exc_info.value) == f"stream_terminal_error:{expected}"


def test_filled_composer_is_expected_before_initial_send(tmp_path, monkeypatch):
    _state_file(tmp_path, monkeypatch)
    executor = _FakeExecutor()
    monkeypatch.setattr(guard, "_wait_existing_cooldown", lambda _executor: True)
    monkeypatch.setattr(guard, "_surface_reason", lambda _executor: "composer_not_empty")

    guard.guard_before_initial_send(executor)


def test_ambiguous_chatgpt_retry_is_terminal_422_and_never_resends(tmp_path, monkeypatch):
    _state_file(tmp_path, monkeypatch)
    executor = _FakeExecutor()
    monkeypatch.setattr(guard, "_surface_reason", lambda _executor: "none")

    with pytest.raises(WorkflowError) as exc_info:
        guard.guard_before_retry(executor)

    text = str(exc_info.value)
    assert text == (
        "stream_terminal_error:422 Unprocessable Entity: "
        "chatgpt_send_submission_unknown"
    )
    metadata = resolve_error_metadata(exc_info.value)
    assert metadata is not None
    assert metadata.code == "unprocessable_entity"
    assert metadata.status_code == 422
    assert metadata.retryable is False


def test_rate_limited_retry_propagates_terminal_429_and_never_resends(tmp_path, monkeypatch):
    path = _state_file(tmp_path, monkeypatch)
    executor = _FakeExecutor()
    monkeypatch.setattr(guard, "_surface_reason", lambda _executor: "rate_limited")
    monkeypatch.setattr(
        guard,
        "_ack_rate_limit",
        lambda _executor: {"detected": True, "dismissed": True},
    )

    with pytest.raises(WorkflowError) as exc_info:
        guard.guard_before_retry(executor)

    assert str(exc_info.value) == (
        "stream_terminal_error:429 Too Many Requests: "
        "chatgpt_web_rate_limited"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["hits"] == 1


def test_non_chatgpt_transport_keeps_existing_retry_behavior(tmp_path, monkeypatch):
    _state_file(tmp_path, monkeypatch)
    executor = _FakeExecutor(url="https://example.com/")
    monkeypatch.setattr(
        guard,
        "_surface_reason",
        lambda _executor: (_ for _ in ()).throw(AssertionError("should not probe")),
    )

    guard.guard_before_initial_send(executor)
    guard.guard_before_retry(executor)


def test_rate_limit_status_is_sanitized(tmp_path, monkeypatch):
    _state_file(tmp_path, monkeypatch)
    guard._record_rate_limit(now=2000.0)

    status = guard.rate_limit_status(now=2005.0)

    assert status == {
        "cooldown_active": True,
        "cooldown_remaining_seconds": 15.0,
        "hits": 1,
    }

def test_installed_wait_guard_forwards_extended_wait_kwargs(monkeypatch):
    from app.core.workflow.executor_send import WorkflowExecutorSendMixin

    calls = []

    def fake_wait(self, send_selector, *, wait_timeout_override=None):
        calls.append(
            {
                "selector": send_selector,
                "wait_timeout_override": wait_timeout_override,
            }
        )
        return True

    monkeypatch.setattr(
        WorkflowExecutorSendMixin,
        "_wait_for_send_idle_before_action",
        fake_wait,
    )
    monkeypatch.setattr(guard, "_INSTALLED", False)
    monkeypatch.setattr(
        guard,
        "guard_before_initial_send",
        lambda executor: calls.append({"guarded": executor}),
    )

    guard.install_chatgpt_web_rate_limit_guard()

    executor = WorkflowExecutorSendMixin.__new__(
        WorkflowExecutorSendMixin
    )
    result = executor._wait_for_send_idle_before_action(
        "css:[data-testid='send-button']",
        wait_timeout_override=300.0,
    )

    assert result is True
    assert calls[0] == {"guarded": executor}
    assert calls[1] == {
        "selector": "css:[data-testid='send-button']",
        "wait_timeout_override": 300.0,
    }

