from __future__ import annotations

import pytest

from app.services import chatgpt_web_prepare as prepare
from app.services.chatgpt_web_surface import SurfaceSnapshot


class _FakeTab:
    pass


def _state(
    *,
    pathname_class: str = "root",
    surface_kind: str = "chat",
    composer_empty: bool = True,
    blocking_reason: str = "none",
    prompt_present: bool = True,
    send_control_present: bool = True,
) -> SurfaceSnapshot:
    return SurfaceSnapshot(
        target_count=1,
        host_ok=True,
        pathname_class=pathname_class,
        surface_kind=surface_kind,
        prompt_present=prompt_present,
        composer_chars=0 if composer_empty else 5,
        composer_empty=composer_empty,
        send_control_present=send_control_present,
        work_quota_exhausted=blocking_reason == "work_quota_exhausted",
        usage_exhausted=blocking_reason == "usage_exhausted",
        rate_limited=blocking_reason == "rate_limited",
        auth_required=blocking_reason == "auth_required",
        challenge_present=blocking_reason == "challenge",
        surface_ready=blocking_reason == "none",
        blocking_reason=blocking_reason,
    )


def test_existing_conversation_opens_new_chat(monkeypatch):
    tab = _FakeTab()
    monkeypatch.setattr(prepare, "_find_chatgpt_tab", lambda: tab)

    states = iter(
        [
            _state(pathname_class="conversation"),
            _state(pathname_class="root"),
        ]
    )
    monkeypatch.setattr(prepare, "_snapshot", lambda actual_tab: next(states))
    monkeypatch.setattr(
        prepare,
        "_run_js",
        lambda actual_tab, script: {"clicked": True},
    )
    monkeypatch.setattr(prepare.time, "sleep", lambda _seconds: None)

    result = prepare.prepare_chatgpt_fresh_composer(timeout_seconds=1)

    assert result == {
        "prepared": True,
        "opened_new_chat": True,
        "pathname_class": "root",
        "surface_kind": "chat",
        "composer_empty": True,
    }


def test_fresh_composer_is_left_untouched(monkeypatch):
    tab = _FakeTab()
    monkeypatch.setattr(prepare, "_find_chatgpt_tab", lambda: tab)
    monkeypatch.setattr(prepare, "_snapshot", lambda actual_tab: _state())

    result = prepare.prepare_chatgpt_fresh_composer(timeout_seconds=1)

    assert result == {
        "prepared": True,
        "opened_new_chat": False,
        "pathname_class": "root",
        "surface_kind": "chat",
        "composer_empty": True,
    }


def test_work_surface_fails_closed_without_navigation(monkeypatch):
    tab = _FakeTab()
    monkeypatch.setattr(prepare, "_find_chatgpt_tab", lambda: tab)
    monkeypatch.setattr(
        prepare,
        "_snapshot",
        lambda actual_tab: _state(
            surface_kind="work",
            blocking_reason="work_surface",
        ),
    )
    called = []
    monkeypatch.setattr(
        prepare,
        "_run_js",
        lambda *args: called.append(args) or {"clicked": True},
    )

    with pytest.raises(prepare.ChatGPTWebModeError, match="chatgpt_web_work_surface"):
        prepare.prepare_chatgpt_fresh_composer(timeout_seconds=1)

    assert called == []


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        ("work_quota_exhausted", "chatgpt_web_work_quota_exhausted"),
        ("usage_exhausted", "chatgpt_web_usage_exhausted"),
        ("rate_limited", "chatgpt_web_rate_limited"),
        ("auth_required", "chatgpt_web_auth_required"),
        ("challenge", "chatgpt_web_challenge"),
        ("composer_not_empty", "chatgpt_web_composer_not_empty"),
    ],
)
def test_blocked_fresh_surface_fails_before_navigation(monkeypatch, reason, code):
    tab = _FakeTab()
    monkeypatch.setattr(prepare, "_find_chatgpt_tab", lambda: tab)
    monkeypatch.setattr(
        prepare,
        "_snapshot",
        lambda actual_tab: _state(
            composer_empty=reason != "composer_not_empty",
            blocking_reason=reason,
        ),
    )

    with pytest.raises(prepare.ChatGPTWebModeError, match=code):
        prepare.prepare_chatgpt_fresh_composer(timeout_seconds=1)


def test_existing_conversation_fails_closed_when_new_chat_control_is_missing(monkeypatch):
    tab = _FakeTab()
    monkeypatch.setattr(prepare, "_find_chatgpt_tab", lambda: tab)
    monkeypatch.setattr(
        prepare,
        "_snapshot",
        lambda actual_tab: _state(pathname_class="conversation"),
    )
    monkeypatch.setattr(
        prepare,
        "_run_js",
        lambda actual_tab, script: {"clicked": False},
    )

    with pytest.raises(
        prepare.ChatGPTWebModeError,
        match="safe new-chat control was not found uniquely",
    ):
        prepare.prepare_chatgpt_fresh_composer(timeout_seconds=1)


def test_new_chat_must_finish_on_ready_chat_surface(monkeypatch):
    tab = _FakeTab()
    monkeypatch.setattr(prepare, "_find_chatgpt_tab", lambda: tab)

    states = iter(
        [
            _state(pathname_class="conversation"),
            _state(
                pathname_class="root",
                composer_empty=False,
                blocking_reason="composer_not_empty",
            ),
        ]
    )
    monkeypatch.setattr(
        prepare,
        "_snapshot",
        lambda actual_tab: next(
            states,
            _state(
                pathname_class="root",
                composer_empty=False,
                blocking_reason="composer_not_empty",
            ),
        ),
    )
    monkeypatch.setattr(
        prepare,
        "_run_js",
        lambda actual_tab, script: {"clicked": True},
    )
    monkeypatch.setattr(prepare.time, "sleep", lambda _seconds: None)

    with pytest.raises(prepare.ChatGPTWebModeError, match="did not reach a safe fresh"):
        prepare.prepare_chatgpt_fresh_composer(timeout_seconds=0.5)
