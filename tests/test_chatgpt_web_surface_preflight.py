from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import chatgpt_surface_preflight as preflight


class _Element:
    def __init__(self, tab):
        self.tab = tab

    def click(self, *, by_js=False, timeout=0, wait_stop=True):
        assert by_js is False
        assert wait_stop is True
        self.tab.clicks += 1
        return self.tab.physical_click_result


class _Tab:
    def __init__(self, switch_result=None, *, physical_click_result=True, marker_found=True):
        self.clicks = 0
        self.physical_click_result = physical_click_result
        self.marker_found = marker_found
        self.switch_result = switch_result or {
            "marked": True,
            "strategy": "interactive",
            "interactive_matches": 1,
            "paired_matches": 0,
            "segment_matches": 1,
        }

    def run_js(self, script):
        if script == preflight._SWITCH_CHAT_JS:
            return dict(self.switch_result)
        if script == preflight._CLEAN_SWITCH_MARKER_JS:
            return True
        if script == preflight._RATE_LIMIT_ACK_JS:
            return {
                "marked": True,
                "dialogs": 1,
                "ack_matches": 1,
            }
        if script == preflight._CLEAN_RATE_LIMIT_ACK_MARKER_JS:
            return True
        raise AssertionError("unexpected script")

    def ele(self, locator, timeout=0):
        if locator == f"css:{preflight._SWITCH_MARKER_SELECTOR}":
            return _Element(self) if self.marker_found else None
        if locator == f"css:{preflight._RATE_LIMIT_ACK_MARKER_SELECTOR}":
            return _Element(self) if self.marker_found else None
        raise AssertionError("unexpected locator")


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
    states = iter([
        _state(kind="unknown", ready=False, reason="prompt_missing", prompt=False),
        _state(kind="chat", ready=True, reason="none", prompt=True),
    ])
    monkeypatch.setattr(preflight, "controlled_chatgpt_tabs", lambda: [tab])
    monkeypatch.setattr(preflight, "inspect_chatgpt_surface", lambda *_args, **_kwargs: next(states))
    _fast_stable(monkeypatch)

    rc = preflight.run(timeout_seconds=1)

    assert rc == 0
    assert tab.clicks == 0
    assert '"ok": true' in capsys.readouterr().out


def test_fresh_target_waits_for_delayed_work_badge_before_freezing_ready_chat(monkeypatch, capsys):
    tab = _Tab()
    states = iter([
        _state(kind="chat", ready=True, reason="none", empty=True),
        _state(kind="work", ready=False, reason="work_surface", empty=True),
        _state(kind="chat", ready=True, reason="none", empty=True),
        _state(kind="chat", ready=True, reason="none", empty=True),
    ])
    monkeypatch.setattr(preflight, "controlled_chatgpt_tabs", lambda: [tab])
    monkeypatch.setattr(preflight, "inspect_chatgpt_surface", lambda *_args, **_kwargs: next(states))
    _fast_stable(monkeypatch, samples=2)

    rc = preflight.run(timeout_seconds=1)

    assert rc == 0
    assert tab.clicks == 1
    out = capsys.readouterr().out
    assert '"ok": true' in out
    assert '"switch_to_chat"' in out


def test_fresh_target_waits_for_delayed_work_badge_before_freezing_dirty_chat(monkeypatch, capsys):
    tab = _Tab()
    states = iter([
        _state(kind="chat", ready=False, reason="composer_not_empty", empty=False),
        _state(kind="work", ready=False, reason="work_surface", empty=True),
        _state(kind="chat", ready=True, reason="none", empty=True),
    ])
    monkeypatch.setattr(preflight, "controlled_chatgpt_tabs", lambda: [tab])
    monkeypatch.setattr(preflight, "inspect_chatgpt_surface", lambda *_args, **_kwargs: next(states))
    _fast_stable(monkeypatch)

    rc = preflight.run(timeout_seconds=1)

    assert rc == 0
    assert tab.clicks == 1
    out = capsys.readouterr().out
    assert '"ok": true' in out
    assert '"switch_to_chat"' in out


def test_normalize_switches_work_to_chat_once_with_physical_click(monkeypatch, capsys):
    tab = _Tab()
    states = iter([
        _state(kind="work", ready=False, reason="work_surface"),
        _state(kind="chat", ready=True, reason="none"),
    ])
    monkeypatch.setattr(preflight, "controlled_chatgpt_tabs", lambda: [tab])
    monkeypatch.setattr(preflight, "inspect_chatgpt_surface", lambda *_args, **_kwargs: next(states))
    _fast_stable(monkeypatch)

    rc = preflight.run(timeout_seconds=1)

    assert rc == 0
    assert tab.clicks == 1
    out = capsys.readouterr().out
    assert '"ok": true' in out
    assert '"switch_to_chat"' in out


def test_segmented_branch_uses_browser_level_click(monkeypatch, capsys):
    tab = _Tab({
        "marked": True,
        "strategy": "paired_segment",
        "interactive_matches": 2,
        "paired_matches": 1,
        "segment_matches": 1,
    })
    states = iter([
        _state(kind="work", ready=False, reason="work_surface"),
        _state(kind="chat", ready=True, reason="none"),
    ])
    monkeypatch.setattr(preflight, "controlled_chatgpt_tabs", lambda: [tab])
    monkeypatch.setattr(preflight, "inspect_chatgpt_surface", lambda *_args, **_kwargs: next(states))
    _fast_stable(monkeypatch)

    rc = preflight.run(timeout_seconds=1)

    assert rc == 0
    assert tab.clicks == 1
    out = capsys.readouterr().out
    assert '"strategy": "paired_segment"' in out
    assert '"segment_matches": 1' in out


def test_missing_marker_fails_without_claiming_switch(monkeypatch, capsys):
    tab = _Tab(marker_found=False)
    monkeypatch.setattr(preflight, "controlled_chatgpt_tabs", lambda: [tab])
    monkeypatch.setattr(
        preflight,
        "inspect_chatgpt_surface",
        lambda *_args, **_kwargs: _state(kind="work", ready=False, reason="work_surface"),
    )
    _fast_stable(monkeypatch)

    rc = preflight.run(timeout_seconds=1)

    assert rc == 1
    assert tab.clicks == 0
    out = capsys.readouterr().out
    assert '"failure_class": "chatgpt_work_surface"' in out
    assert '"actions": []' in out


def test_transient_unknown_empty_surface_waits_for_mode_chrome(monkeypatch, capsys):
    tab = _Tab()
    states = iter([
        _state(
            kind="unknown",
            ready=False,
            reason="unknown_surface",
            empty=True,
            prompt=True,
        ),
        _state(kind="chat", ready=True, reason="none"),
    ])
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
    assert '"switch_to_chat"' not in capsys.readouterr().out


def test_persistent_ambiguous_empty_surface_can_normalize_through_exact_chat(
    monkeypatch,
    capsys,
):
    tab = _Tab()
    initial = _state(
        kind="unknown",
        ready=False,
        reason="unknown_surface",
        empty=True,
        prompt=True,
    )
    settled = _state(kind="chat", ready=True, reason="none")
    monkeypatch.setattr(preflight, "controlled_chatgpt_tabs", lambda: [tab])
    monkeypatch.setattr(
        preflight,
        "_wait_initial_surface",
        lambda *_args, **_kwargs: initial,
    )
    monkeypatch.setattr(
        preflight,
        "_wait_after_chat_switch",
        lambda *_args, **_kwargs: settled,
    )

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
        lambda *_args, **_kwargs: _state(kind="unknown", ready=False, reason="unknown_surface", empty=False),
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
        lambda *_args, **_kwargs: _state(kind="chat", ready=False, reason="composer_not_empty", empty=False),
    )
    _fast_stable(monkeypatch)

    rc = preflight.run(timeout_seconds=1)

    assert rc == 1
    assert tab.clicks == 0
    assert '"failure_class": "chatgpt_composer_not_empty"' in capsys.readouterr().out


def test_existing_conversation_opens_new_chat_once(monkeypatch, capsys):
    tab = _Tab()
    states = iter([
        _state(kind="chat", pathname="conversation", ready=True),
        _state(kind="chat", pathname="root", ready=True),
    ])
    monkeypatch.setattr(preflight, "controlled_chatgpt_tabs", lambda: [tab])
    monkeypatch.setattr(preflight, "inspect_chatgpt_surface", lambda *_args, **_kwargs: next(states))
    monkeypatch.setattr(preflight, "prepare_chatgpt_fresh_composer", lambda **_kwargs: {"opened_new_chat": True})
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
        lambda *_args, **_kwargs: _state(kind="work", ready=False, reason="work_quota_exhausted"),
    )
    _fast_stable(monkeypatch)

    rc = preflight.run(timeout_seconds=1)

    assert rc == 1
    assert tab.clicks == 0
    assert '"failure_class": "chatgpt_work_quota_exhausted"' in capsys.readouterr().out

def test_stale_rate_limit_notice_is_dismissed_then_preflight_continues(
    monkeypatch,
    capsys,
):
    tab = _Tab()
    initial = _state(
        kind="chat",
        ready=False,
        reason="rate_limited",
        empty=True,
    )
    settled = _state(
        kind="chat",
        ready=True,
        reason="none",
        empty=True,
    )

    monkeypatch.setattr(
        preflight,
        "controlled_chatgpt_tabs",
        lambda: [tab],
    )
    monkeypatch.setattr(
        preflight,
        "_wait_initial_surface",
        lambda *_args, **_kwargs: initial,
    )
    monkeypatch.setattr(
        preflight,
        "_wait_after_rate_limit_dismiss",
        lambda *_args, **_kwargs: settled,
    )

    rc = preflight.run(timeout_seconds=1)

    assert rc == 0
    assert tab.clicks == 1
    out = capsys.readouterr().out
    assert '"dismiss_rate_limit_notice"' in out
    assert '"ok": true' in out


def test_persistent_rate_limit_still_fails_closed_after_ack_dismiss(
    monkeypatch,
    capsys,
):
    tab = _Tab()
    limited = _state(
        kind="chat",
        ready=False,
        reason="rate_limited",
        empty=True,
    )

    monkeypatch.setattr(
        preflight,
        "controlled_chatgpt_tabs",
        lambda: [tab],
    )
    monkeypatch.setattr(
        preflight,
        "_wait_initial_surface",
        lambda *_args, **_kwargs: limited,
    )
    monkeypatch.setattr(
        preflight,
        "_wait_after_rate_limit_dismiss",
        lambda *_args, **_kwargs: limited,
    )

    rc = preflight.run(timeout_seconds=1)

    assert rc == 1
    assert tab.clicks == 1
    out = capsys.readouterr().out
    assert '"dismiss_rate_limit_notice"' in out
    assert '"failure_class": "chatgpt_web_rate_limited"' in out


def test_rate_limit_without_unique_ack_does_not_click(monkeypatch, capsys):
    tab = _Tab()
    limited = _state(
        kind="chat",
        ready=False,
        reason="rate_limited",
        empty=True,
    )

    monkeypatch.setattr(
        preflight,
        "controlled_chatgpt_tabs",
        lambda: [tab],
    )
    monkeypatch.setattr(
        preflight,
        "_wait_initial_surface",
        lambda *_args, **_kwargs: limited,
    )
    monkeypatch.setattr(
        preflight,
        "_physical_click_rate_limit_ack",
        lambda *_args, **_kwargs: False,
    )

    rc = preflight.run(timeout_seconds=1)

    assert rc == 1
    assert tab.clicks == 0
    out = capsys.readouterr().out
    assert '"actions": []' in out
    assert '"failure_class": "chatgpt_web_rate_limited"' in out

