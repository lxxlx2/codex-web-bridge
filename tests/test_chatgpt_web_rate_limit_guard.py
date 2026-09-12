from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import WorkflowError
from app.services import chatgpt_web_rate_limit_guard as guard
from app.services.error_metadata import resolve_error_metadata


class _FakeTab:
    def __init__(
        self,
        *,
        url: str = "https://chatgpt.com/",
        detected: bool = False,
        detections: list[bool] | None = None,
    ):
        self.url = url
        self.detected = detected
        self.detections = list(detections or [])
        self.calls = 0

    def run_js(self, _script):
        self.calls += 1
        detected = self.detections.pop(0) if self.detections else self.detected
        return {
            "detected": detected,
            "dismissed": detected,
        }


class _FakeExecutor:
    def __init__(self, tab: _FakeTab, *, cancelled: bool = False):
        self.tab = tab
        self.cancelled = cancelled

    def _check_cancelled(self):
        return self.cancelled


def _state_file(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "rate-limit.json"
    monkeypatch.setenv("UWA_CHATGPT_RATE_LIMIT_STATE", str(path))
    return path


def test_pre_submit_rate_limit_waits_then_allows_one_initial_send(tmp_path, monkeypatch):
    path = _state_file(tmp_path, monkeypatch)
    executor = _FakeExecutor(_FakeTab(detections=[True, False]))
    waits: list[str] = []

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
    assert executor.tab.calls == 2


def test_persistent_pre_submit_rate_limit_propagates_terminal_429(tmp_path, monkeypatch):
    path = _state_file(tmp_path, monkeypatch)
    executor = _FakeExecutor(_FakeTab(detections=[True, True]))
    monkeypatch.setattr(guard, "_wait_existing_cooldown", lambda _executor: True)

    with pytest.raises(WorkflowError) as exc_info:
        guard.guard_before_initial_send(executor)

    text = str(exc_info.value)
    assert text == "429 Too Many Requests: chatgpt_web_rate_limited"
    metadata = resolve_error_metadata(exc_info.value)
    assert metadata is not None
    assert metadata.code == "rate_limit_exceeded"
    assert metadata.status_code == 429
    assert metadata.retryable is False
    assert metadata.error_type == "rate_limit_error"

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["hits"] == 1
    assert executor.tab.calls == 2


def test_pre_submit_cancellation_unwinds_without_send(tmp_path, monkeypatch):
    _state_file(tmp_path, monkeypatch)
    executor = _FakeExecutor(_FakeTab(detected=False), cancelled=True)

    with pytest.raises(WorkflowError, match="request_cancelled"):
        guard.guard_before_initial_send(executor)

    assert executor.tab.calls == 0


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


def test_ambiguous_chatgpt_retry_is_terminal_422_and_never_resends(tmp_path, monkeypatch):
    _state_file(tmp_path, monkeypatch)
    executor = _FakeExecutor(_FakeTab(detected=False))

    with pytest.raises(WorkflowError) as exc_info:
        guard.guard_before_retry(executor)

    text = str(exc_info.value)
    assert text == "422 Unprocessable Entity: chatgpt_send_submission_unknown"
    metadata = resolve_error_metadata(exc_info.value)
    assert metadata is not None
    assert metadata.code == "unprocessable_entity"
    assert metadata.status_code == 422
    assert metadata.retryable is False
    assert executor.tab.calls == 1


def test_rate_limited_retry_propagates_terminal_429_and_never_resends(tmp_path, monkeypatch):
    path = _state_file(tmp_path, monkeypatch)
    executor = _FakeExecutor(_FakeTab(detected=True))

    with pytest.raises(WorkflowError) as exc_info:
        guard.guard_before_retry(executor)

    text = str(exc_info.value)
    assert text == "429 Too Many Requests: chatgpt_web_rate_limited"
    metadata = resolve_error_metadata(exc_info.value)
    assert metadata is not None
    assert metadata.code == "rate_limit_exceeded"
    assert metadata.status_code == 429
    assert metadata.retryable is False

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["hits"] == 1
    assert executor.tab.calls == 1


def test_non_chatgpt_transport_keeps_existing_retry_behavior(tmp_path, monkeypatch):
    _state_file(tmp_path, monkeypatch)
    executor = _FakeExecutor(
        _FakeTab(
            url="https://example.com/",
            detected=True,
        )
    )

    guard.guard_before_initial_send(executor)
    guard.guard_before_retry(executor)
    assert executor.tab.calls == 0


def test_rate_limit_status_is_sanitized(tmp_path, monkeypatch):
    _state_file(tmp_path, monkeypatch)
    guard._record_rate_limit(now=2000.0)

    status = guard.rate_limit_status(now=2005.0)

    assert status == {
        "cooldown_active": True,
        "cooldown_remaining_seconds": 15.0,
        "hits": 1,
    }
