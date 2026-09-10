from app.services import chatgpt_web_prepare as prepare


class _FakeTab:
    pass


def test_existing_conversation_opens_new_chat(monkeypatch):
    tab = _FakeTab()
    monkeypatch.setattr(prepare, "_find_chatgpt_tab", lambda: tab)

    probes = iter(
        [
            {"pathname": "/c/example", "prompt": True},
            {"pathname": "/", "prompt": True},
        ]
    )
    calls = []

    def fake_run_js(actual_tab, script):
        assert actual_tab is tab
        calls.append(script)
        if script == prepare._PROBE_JS:
            return next(probes)
        if script == prepare._NEW_CHAT_JS:
            return {"clicked": True, "pathname": "/c/example"}
        raise AssertionError("unexpected script")

    monkeypatch.setattr(prepare, "_run_js", fake_run_js)
    monkeypatch.setattr(prepare.time, "sleep", lambda _seconds: None)

    result = prepare.prepare_chatgpt_fresh_composer(timeout_seconds=1)

    assert result == {
        "prepared": True,
        "opened_new_chat": True,
        "pathname": "/",
    }
    assert prepare._NEW_CHAT_JS in calls


def test_fresh_composer_is_left_untouched(monkeypatch):
    tab = _FakeTab()
    monkeypatch.setattr(prepare, "_find_chatgpt_tab", lambda: tab)
    monkeypatch.setattr(
        prepare,
        "_run_js",
        lambda actual_tab, script: {"pathname": "/", "prompt": True},
    )

    result = prepare.prepare_chatgpt_fresh_composer(timeout_seconds=1)

    assert result == {
        "prepared": True,
        "opened_new_chat": False,
        "pathname": "/",
    }


def test_existing_conversation_fails_closed_when_new_chat_control_is_missing(monkeypatch):
    tab = _FakeTab()
    monkeypatch.setattr(prepare, "_find_chatgpt_tab", lambda: tab)

    def fake_run_js(actual_tab, script):
        if script == prepare._PROBE_JS:
            return {"pathname": "/c/example", "prompt": True}
        if script == prepare._NEW_CHAT_JS:
            return {"clicked": False, "pathname": "/c/example"}
        raise AssertionError("unexpected script")

    monkeypatch.setattr(prepare, "_run_js", fake_run_js)

    try:
        prepare.prepare_chatgpt_fresh_composer(timeout_seconds=1)
    except prepare.ChatGPTWebModeError as exc:
        assert "safe new-chat control was not found" in str(exc)
    else:
        raise AssertionError("expected ChatGPTWebModeError")
