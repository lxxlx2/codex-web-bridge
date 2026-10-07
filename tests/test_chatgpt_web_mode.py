import pytest

from app.services.chatgpt_web_mode import (
    ChatGPTWebModeError,
    default_reasoning_effort,
    normalize_reasoning_effort,
    target_web_model,
    temporary_chat_enabled,
    web_mode_strict,
)
from app.services import chatgpt_web_mode as web_mode


def test_web_mode_defaults_to_sol_high_and_temporary_chat(monkeypatch):
    for key in (
        "UWA_CODEX_WEB_MODEL",
        "UWA_CODEX_REASONING_DEFAULT",
        "UWA_CODEX_TEMPORARY_CHAT",
        "UWA_CODEX_WEB_MODE_STRICT",
    ):
        monkeypatch.delenv(key, raising=False)

    assert target_web_model() == "auto-best"
    assert default_reasoning_effort() == "max"
    assert normalize_reasoning_effort(None) == "max"
    assert temporary_chat_enabled() is True
    assert web_mode_strict() is True


def test_reasoning_medium_and_high_are_supported(monkeypatch):
    monkeypatch.setenv("UWA_CODEX_REASONING_DEFAULT", "high")
    assert normalize_reasoning_effort({"effort": "medium"}) == "medium"
    assert normalize_reasoning_effort({"effort": "high"}) == "high"
    assert normalize_reasoning_effort("medium") == "medium"
    assert normalize_reasoning_effort("high") == "high"


def test_unverified_reasoning_levels_fail_closed(monkeypatch):
    monkeypatch.setenv("UWA_CODEX_REASONING_DEFAULT", "high")
    with pytest.raises(ChatGPTWebModeError, match="supported=medium,high"):
        normalize_reasoning_effort({"effort": "ultra"})


@pytest.mark.parametrize("selected_model", ["GPT-5.6 Sol", None])
def test_model_verification_reads_checked_picker_option_and_closes_menu(
    monkeypatch, selected_model
):
    calls = []
    menu = {"state": "closed"}

    def run_js(_tab, script, *_args):
        calls.append(script)
        if script == web_mode._STATE_JS:
            return (
                {"model": selected_model, "reasoning": "high", "temporary_chat": True}
                if menu["state"] == "open"
                else {"model": None, "reasoning": None, "temporary_chat": True}
            )
        if script == web_mode._MODEL_MENU_STATE_JS:
            return menu["state"]
        if script == web_mode._MODEL_OPTIONS_JS:
            return ([{"label": selected_model, "checked": True, "disabled": False}]
                    if selected_model else [])
        if script == web_mode._REASONING_DETAILS_JS:
            return {"min": 0, "max": 2, "now": 2}
        raise AssertionError("unexpected script")

    def click(*_args, **_kwargs):
        menu["state"] = "open"
        return {"clicked": True}

    def close(*_args):
        menu["state"] = "closed"
        return True

    monkeypatch.setattr(web_mode, "target_web_model", lambda: "GPT-5.6 Sol")
    monkeypatch.setattr(web_mode, "_run_js", run_js)
    monkeypatch.setattr(web_mode, "_click", click)
    monkeypatch.setattr(web_mode, "_close_model_menu", close)
    monkeypatch.setattr(web_mode.time, "sleep", lambda *_args: None)

    state = web_mode.inspect_chatgpt_web_mode(object())

    assert state["model"] == selected_model
    assert state["reasoning"] == "high"
    assert state["temporary_chat"] is True
    assert calls.count(web_mode._STATE_JS) >= 2
    assert menu["state"] == "closed"


def test_temporary_chat_only_clicks_explicit_inactive_control(monkeypatch):
    clicks = []
    monkeypatch.setattr(web_mode, "inspect_chatgpt_web_mode", lambda _tab: {"temporary_chat": None})
    monkeypatch.setattr(web_mode, "_click", lambda *_args, **kwargs: clicks.append(kwargs))
    web_mode._ensure_temporary_chat(object())
    assert clicks == []

    monkeypatch.setattr(web_mode, "inspect_chatgpt_web_mode", lambda _tab: {"temporary_chat": False})
    monkeypatch.setattr(web_mode, "_click", lambda *_args, **kwargs: clicks.append(kwargs) or {"clicked": False})
    web_mode._ensure_temporary_chat(object())
    assert clicks[0]["aria_exact"] == ["临时聊天", "temporary chat"]


def test_reasoning_slider_moves_one_step_and_reads_back(monkeypatch):
    value = {"now": 1}
    keys = []

    class Actions:
        def key_down(self, key):
            keys.append(key)
            value["now"] += 1 if key == "RIGHT" else -1
            return self

        def key_up(self, key):
            keys.append(key)
            return self

    class Slider:
        def click(self):
            return None

    class Tab:
        actions = Actions()

        def ele(self, selector):
            assert '[role="slider"]' in selector
            return Slider()

    monkeypatch.setattr(web_mode, "target_web_model", lambda: "GPT-5.6 Sol")
    monkeypatch.setattr(web_mode, "inspect_chatgpt_web_mode", lambda _tab: {"reasoning": "medium"})
    monkeypatch.setattr(web_mode, "_open_reasoning_menu", lambda _tab: True)
    monkeypatch.setattr(web_mode, "_close_model_menu", lambda _tab: True)
    monkeypatch.setattr(web_mode, "_run_js", lambda _tab, script: {"min": 0, "max": 2, "now": value["now"]} if script == web_mode._REASONING_DETAILS_JS else None)
    monkeypatch.setattr(web_mode.time, "sleep", lambda *_args: None)

    assert web_mode._ensure_reasoning(Tab(), "high") is True
    assert value["now"] == 2
    assert keys == ["RIGHT", "RIGHT"]


def test_reasoning_slider_fails_closed_without_verified_value(monkeypatch):
    monkeypatch.setattr(web_mode, "target_web_model", lambda: "GPT-5.6 Sol")
    monkeypatch.setattr(web_mode, "inspect_chatgpt_web_mode", lambda _tab: {"reasoning": "medium"})
    monkeypatch.setattr(web_mode, "_open_reasoning_menu", lambda _tab: True)
    monkeypatch.setattr(web_mode, "_close_model_menu", lambda _tab: True)
    monkeypatch.setattr(web_mode, "_run_js", lambda _tab, _script: None)
    assert web_mode._ensure_reasoning(object(), "high") is False
    assert web_mode._verification_errors(
        {"model": "GPT-5.6 Sol", "reasoning": "medium", "temporary_chat": True},
        "high",
        reasoning_verified=True,
    ) == ["reasoning expected='high' actual='medium'"]
