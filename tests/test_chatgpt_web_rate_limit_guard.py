from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import WorkflowError
from app.services import chatgpt_web_rate_limit_guard as guard


class _FakeTab:
    def __init__(self, *, url: str = "https://chatgpt.com/", detected: bool = False):
        self.url = url
        self.detected = detected
        self.calls = 0

    def run_js(self, _script):
        self.calls += 1
        return {
            "detected": self.detected,
            "dismissed": self.detected,
        }


class _FakeExecutor:
    def __init__(self, tab: _FakeTab):
        self.tab = tab

    def _check_cancelled(self):
        return False


def _state_file(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "rate-limit.json"
    monkeypatch.setenv("UWA_CHATGPT_RATE_LIMIT_STATE", str(path))
    return path


def test_rate_limit_detection_arms_persisted_cooldown(tmp_path, monkeypatch):
    path = _state_file(tmp_path, monkeypatch)
    executor = _FakeExecutor(_FakeTab(detected=True))

    with pytest.raises(WorkflowError, match="chatgpt_web_rate_limited"):
        guard.guard_before_initial_send(executor)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["hits"] == 1
    assert data["backoff_seconds"] == 20.0
    assert data["blocked_until_epoch"] > data["last_seen_epoch"]


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


def test_ambiguous_chatgpt_retry_is_suppressed(tmp_path, monkeypatch):
    _state_file(tmp_path, monkeypatch)
    executor = _FakeExecutor(_FakeTab(detected=False))

    with pytest.raises(WorkflowError, match="chatgpt_send_submission_unknown"):
        guard.guard_before_retry(executor)


def test_rate_limited_retry_never_resends(tmp_path, monkeypatch):
    path = _state_file(tmp_path, monkeypatch)
    executor = _FakeExecutor(_FakeTab(detected=True))

    with pytest.raises(WorkflowError, match="chatgpt_web_rate_limited"):
        guard.guard_before_retry(executor)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["hits"] == 1


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
