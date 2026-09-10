from app.services import codex_web_policy as policy


def test_ultra_aliases_to_high(monkeypatch):
    monkeypatch.setattr(policy, "default_reasoning_effort", lambda: "high")
    assert policy.normalize_codex_reasoning("ultra") == "high"
    assert policy.normalize_codex_reasoning({"effort": "xhigh"}) == "high"


def test_verified_high_implies_sol_when_model_dom_is_hidden(monkeypatch):
    monkeypatch.setattr(policy, "target_web_model", lambda: "GPT-5.6 Sol")
    monkeypatch.setattr(policy, "temporary_chat_enabled", lambda: True)
    monkeypatch.setattr(policy, "temporary_chat_strict", lambda: False)

    result = policy.evaluate_codex_web_state(
        {
            "model": None,
            "reasoning": "high",
            "temporary_chat": None,
            "target_model": "GPT-5.6 Sol",
        },
        "high",
    )

    assert result["verified"] is True
    assert result["model"] == "GPT-5.6 Sol"
    assert result["model_verified"] is True
    assert result["model_verification"] == "official-reasoning-mapping"
    assert result["temporary_chat_verified"] is False


def test_reasoning_mismatch_still_fails_strict_verification(monkeypatch):
    monkeypatch.setattr(policy, "target_web_model", lambda: "GPT-5.6 Sol")
    monkeypatch.setattr(policy, "temporary_chat_enabled", lambda: True)
    monkeypatch.setattr(policy, "temporary_chat_strict", lambda: False)

    result = policy.evaluate_codex_web_state(
        {
            "model": None,
            "reasoning": "medium",
            "temporary_chat": None,
        },
        "high",
    )

    assert result["verified"] is False
    assert any("reasoning expected='high'" in item for item in result["verification_errors"])


def test_temporary_chat_can_be_made_strict(monkeypatch):
    monkeypatch.setattr(policy, "target_web_model", lambda: "GPT-5.6 Sol")
    monkeypatch.setattr(policy, "temporary_chat_enabled", lambda: True)
    monkeypatch.setattr(policy, "temporary_chat_strict", lambda: True)

    result = policy.evaluate_codex_web_state(
        {
            "model": None,
            "reasoning": "high",
            "temporary_chat": None,
        },
        "high",
    )

    assert result["verified"] is False
    assert any("temporary_chat expected=True" in item for item in result["verification_errors"])
