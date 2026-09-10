import pytest

from app.services.chatgpt_web_mode import (
    ChatGPTWebModeError,
    default_reasoning_effort,
    normalize_reasoning_effort,
    target_web_model,
    temporary_chat_enabled,
    web_mode_strict,
)


def test_web_mode_defaults_to_sol_high_and_temporary_chat(monkeypatch):
    for key in (
        "UWA_CODEX_WEB_MODEL",
        "UWA_CODEX_REASONING_DEFAULT",
        "UWA_CODEX_TEMPORARY_CHAT",
        "UWA_CODEX_WEB_MODE_STRICT",
    ):
        monkeypatch.delenv(key, raising=False)

    assert target_web_model() == "GPT-5.6 Sol"
    assert default_reasoning_effort() == "high"
    assert normalize_reasoning_effort(None) == "high"
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
