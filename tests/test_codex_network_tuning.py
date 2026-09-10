from app.services.codex_network_tuning import (
    _tuned_stream_config,
    codex_chatgpt_first_content_timeout,
    codex_chatgpt_post_content_silence_timeout,
)


class _Parser:
    def __init__(self, parser_id):
        self.parser_id = parser_id

    def get_id(self):
        return self.parser_id


def test_chatgpt_high_wait_budgets_are_long_by_default(monkeypatch):
    monkeypatch.delenv("UWA_CODEX_CHATGPT_FIRST_CONTENT_TIMEOUT_SEC", raising=False)
    monkeypatch.delenv("UWA_CODEX_CHATGPT_POST_CONTENT_SILENCE_SEC", raising=False)

    assert codex_chatgpt_first_content_timeout() == 180.0
    assert codex_chatgpt_post_content_silence_timeout() == 60.0


def test_chatgpt_stream_config_gets_codex_wait_budgets(monkeypatch):
    monkeypatch.setenv("UWA_CODEX_CHATGPT_FIRST_CONTENT_TIMEOUT_SEC", "120")
    monkeypatch.setenv("UWA_CODEX_CHATGPT_POST_CONTENT_SILENCE_SEC", "45")
    original = {
        "hard_timeout": 600,
        "network": {
            "silence_threshold": 2,
            "response_interval": 0.5,
        },
    }

    tuned = _tuned_stream_config(original, _Parser("chatgpt"))

    assert tuned["network"]["first_content_timeout"] == 120.0
    assert tuned["network"]["post_content_silence_threshold"] == 45.0
    assert original["network"].get("first_content_timeout") is None
    assert original["network"].get("post_content_silence_threshold") is None


def test_existing_longer_chatgpt_budget_is_not_reduced(monkeypatch):
    monkeypatch.setenv("UWA_CODEX_CHATGPT_FIRST_CONTENT_TIMEOUT_SEC", "120")
    monkeypatch.setenv("UWA_CODEX_CHATGPT_POST_CONTENT_SILENCE_SEC", "45")

    tuned = _tuned_stream_config(
        {
            "network": {
                "first_content_timeout": 240,
                "post_content_silence_threshold": 90,
            }
        },
        _Parser("chatgpt"),
    )

    assert tuned["network"]["first_content_timeout"] == 240.0
    assert tuned["network"]["post_content_silence_threshold"] == 90.0


def test_other_parsers_are_untouched(monkeypatch):
    monkeypatch.setenv("UWA_CODEX_CHATGPT_FIRST_CONTENT_TIMEOUT_SEC", "180")
    original = {"network": {"silence_threshold": 3}}

    tuned = _tuned_stream_config(original, _Parser("gemini"))

    assert tuned is original
