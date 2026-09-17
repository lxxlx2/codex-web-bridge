from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import chatgpt_surface_preflight as preflight


def _state(*, kind: str, reason: str, empty: bool = True):
    return SimpleNamespace(
        surface_kind=kind,
        blocking_reason=reason,
        composer_empty=empty,
        prompt_present=True,
    )


def test_post_switch_allows_old_work_frame_to_settle_to_chat(monkeypatch):
    states = iter([
        _state(kind="work", reason="work_surface"),
        _state(kind="chat", reason="none"),
    ])
    monkeypatch.setattr(
        preflight,
        "inspect_chatgpt_surface",
        lambda *_args, **_kwargs: next(states),
    )
    monkeypatch.setattr(preflight, "READY_STABLE_SAMPLES", 1)
    monkeypatch.setattr(preflight, "POLL_SECONDS", 0)
    monkeypatch.setattr(preflight.time, "sleep", lambda _seconds: None)

    state = preflight._wait_after_chat_switch(object(), 1)

    assert state.surface_kind == "chat"
    assert state.blocking_reason == "none"


def test_post_switch_still_fails_closed_on_non_mode_blocker(monkeypatch):
    state = _state(kind="unknown", reason="auth_required")
    monkeypatch.setattr(
        preflight,
        "inspect_chatgpt_surface",
        lambda *_args, **_kwargs: state,
    )
    monkeypatch.setattr(preflight, "POLL_SECONDS", 0)
    monkeypatch.setattr(preflight.time, "sleep", lambda _seconds: None)

    result = preflight._wait_after_chat_switch(object(), 1)

    assert result is state
