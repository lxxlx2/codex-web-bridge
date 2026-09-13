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
):
    return SimpleNamespace(
        surface_kind=kind,
        pathname_class=pathname,
        surface_ready=ready,
        blocking_reason=reason,
        composer_empty=empty,
    )


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
    monkeypatch.setattr(preflight.time, "sleep", lambda _seconds: None)

    rc = preflight.run(timeout_seconds=1)

    assert rc == 0
    assert tab.clicks == 1
    out = capsys.readouterr().out
    assert '"ok": true' in out
    assert '"switch_to_chat"' in out


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

    rc = preflight.run(timeout_seconds=1)

    assert rc == 1
    assert tab.clicks == 0
    assert '"failure_class": "chatgpt_work_quota_exhausted"' in capsys.readouterr().out
