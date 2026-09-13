from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import chatgpt_surface_preflight as preflight


class _Tab:
    def __init__(self):
        self.clicks = 0

    def run_js(self, script):
        assert script == preflight._SWITCH_CHAT_JS
        self.clicks += 1
        return {"clicked": True, "matches": 1}


def _state(
    *,
    kind="chat",
    pathname="root",
    ready=True,
    reason="none",
    empty=True,
    prompt=True,
):
    return SimpleNamespace(
        surface_kind=kind,
        pathname_class=pathname,
        surface_ready=ready,
        blocking_reason=reason,
        composer_empty=empty,
        prompt_present=prompt,
    )


def _fast_stable(monkeypatch, samples=1):
    monkeypatch.setattr(preflight, "READY_STABLE_SAMPLES", samples)
    monkeypatch.setattr(preflight, "POLL_SECONDS", 0)
    monkeypatch.setattr(preflight.time, "sleep", lambda _seconds: None)


def test_fresh_target_waits_for_prompt_before_classification(monkeypatch, capsys):
    tab = _Tab()
    states = iter(
        [
            _state(
                kind="unknown",
                ready=False,
                reason="prompt_missing",
                prompt=False,
            ),
            _state(kind="chat", ready=True, reason="none", prompt=True),
        ]
    )
    monkeypatch.setattr(preflight, "controlled_chatgpt_tabs", lambda: [tab])
    monkeypatch.setattr(
        preflight,
        "inspect_chatgpt_surface",
        lambda *_args, **_kwargs: next(states),
    )
    _fast_stable(monkeypatch)

    rc = preflight.run(timeout_seconds=1)

    assert rc == 0
    assert tab.clicks == 0
    assert '"ok": true' in capsys.readouterr().out


def test_fresh_target_waits_for_delayed_work_badge_before_freezing_ready_chat(monkeypatch, capsys):
    tab = _Tab()
    states = iter(
        [
            _state(kind="chat", ready=True, reason="none", empty=True),
            _state(kind="work", ready=False, reason="work_surface", empty=True),
            _state(kind="chat", ready=True, reason="none", empty=True),
            _state(kind="chat", ready=True, reason="none", empty=True),
        ]
    )
    monkeypatch.setattr(preflight, "controlled_chatgpt_tabs", lambda: [tab])
    monkeypatch.setattr(
        preflight,
        "inspect_chatgpt_surface",
        lambda *_args, **_kwargs: next(states),
    )
    _fast_stable(monkeypatch, samples=2)

    rc = preflight.run(timeout_seconds=1)

    assert rc == 0
    assert tab.clicks == 1
    out = capsys.readouterr().out
    assert '"ok": true' in out
    assert '"switch_to_chat"' in out


def test_fresh_target_waits_for_delayed_work_badge_before_freezing_dirty_chat(monkeypatch, capsys):
    tab = _Tab()
    states = iter(
        [
            _state(
                kind="chat",
                ready=False,
                reason="composer_not_empty",
                empty=False,
            ),
            _state(kind="work", ready=False, reason="work_surface", empty=True),
            _state(kind="chat", ready=True, reason="none", empty=True),
        ]
    )
    monkeypatch.setattr(preflight, "controlled_chatgpt_tabs", lambda: [tab])
    monkeypatch.setattr(
        preflight,
        "inspect_chatgpt_surface",
        lambda *_args, **_kwargs: next(states),
    )
    _fast_stable(monkeypatch)

    rc = preflight.run(timeout_seconds=1)

    assert rc == 0
    assert tab.clicks == 1
    out = capsys.readouterr().out
    assert '"ok": true' in out
    assert '"switch_to_chat"' in out


def test_normalize_switches_work_to_chat_once(monkeypatch, capsys):
    tab = _Tab()
    states = iter(
        [
            _state(kind="work", ready=False, reason="work_surface"),
            _state(kind="chat", ready=True, reason="none"),
        ]
    )
    monkeypatch.setattr(preflight, "controlled_chatgpt_tabs", lambda: [tab])
    monkeypatch.setattr(
        preflight,
        "inspect_chatgpt_surface",
        lambda *_args, **_kwargs: next(states),
    )
    _fast_stable(monkeypatch)

    rc = preflight.run(timeout_seconds=1)

    assert rc == 0
    assert tab.clicks == 1
    out = capsys.readouterr().out
    assert '"ok": true' in out
    assert '"switch_to_chat"' in out


def test_ambiguous_empty_surface_can_normalize_through_exact_chat(monkeypatch, capsys):
    tab = _Tab()
    states = iter(
        [
            _state(kind="unknown", ready=False, reason="unknown_surface"),
            _state(kind="chat", ready=True, reason="none"),
        ]
    )
    monkeypatch.setattr(preflight, "controlled_chatgpt_tabs", lambda: [tab])
    monkeypatch.setattr(
        preflight,
        "inspect_chatgpt_surface",
        lambda *_args, **_kwargs: next(states),
    )
    _fast_stable(monkeypatch)

    rc = preflight.run(timeout_seconds=1)

    assert rc == 0
    assert tab.clicks == 1
    assert '"switch_to_chat"' in capsys.readouterr().out


def test_ambiguous_dirty_surface_does_not_click_chat(monkeypatch, capsys):
    tab = _Tab()
    monkeypatch.setattr(preflight, "controlled_chatgpt_tabs", lambda: [tab])
    monkeypatch.setattr(
        preflight,
        "inspect_chatgpt_surface",
        lambda *_args, **_kwargs: _state(
            kind="unknown",
            ready=False,
            reason="unknown_surface",
            empty=False,
        ),
    )
    _fast_stable(monkeypatch)

    rc = preflight.run(timeout_seconds=1)

    assert rc == 1
    assert tab.clicks == 0
    assert '"failure_class": "chatgpt_surface_unknown"' in capsys.readouterr().out


def test_dirty_composer_fails_without_clearing(monkeypatch, capsys):
    tab = _Tab()
    monkeypatch.setattr(preflight, "controlled_chatgpt_tabs", lambda: [tab])
    monkeypatch.setattr(
        preflight,
        "inspect_chatgpt_surface",
        lambda *_args, **_kwargs: _state(
            kind="chat",
            ready=False,
            reason="composer_not_empty",
            empty=False,
        ),
    )
    _fast_stable(monkeypatch)

    rc = preflight.run(timeout_seconds=1)

    assert rc == 1
    assert tab.clicks == 0
    assert '"failure_class": "chatgpt_composer_not_empty"' in capsys.readouterr().out


def test_existing_conversation_opens_new_chat_once(monkeypatch, capsys):
    tab = _Tab()
    states = iter(
        [
            _state(kind="chat", pathname="conversation", ready=True),
            _state(kind="chat", pathname="root", ready=True),
        ]
    )
    monkeypatch.setattr(preflight, "controlled_chatgpt_tabs", lambda: [tab])
    monkeypatch.setattr(
        preflight,
        "inspect_chatgpt_surface",
        lambda *_args, **_kwargs: next(states),
    )
    monkeypatch.setattr(
        preflight,
        "prepare_chatgpt_fresh_composer",
        lambda **_kwargs: {"opened_new_chat": True},
    )
    _fast_stable(monkeypatch)

    rc = preflight.run(timeout_seconds=1)

    assert rc == 0
    assert '"new_chat"' in capsys.readouterr().out


def test_quota_blocker_fails_before_navigation(monkeypatch, capsys):
    tab = _Tab()
    monkeypatch.setattr(preflight, "controlled_chatgpt_tabs", lambda: [tab])
    monkeypatch.setattr(
        preflight,
        "inspect_chatgpt_surface",
        lambda *_args, **_kwargs: _state(
            kind="work",
            ready=False,
            reason="work_quota_exhausted",
        ),
    )
    _fast_stable(monkeypatch)

    rc = preflight.run(timeout_seconds=1)

    assert rc == 1
    assert tab.clicks == 0
    assert '"failure_class": "chatgpt_work_quota_exhausted"' in capsys.readouterr().out
