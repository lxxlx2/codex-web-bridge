import pytest

from app.services import chatgpt_web_mode as web
from app.services import codex_web_policy as policy


def test_real_2026_menu_prefers_sol_over_retiring_gpt55():
    selected = web._best_available_model([
        {"label": "GPT-5.6 Sol", "checked": True, "disabled": False},
        {"label": "GPT-5.5 将于 10月14日下线", "checked": False, "disabled": False},
    ])
    assert selected == {"name": "GPT-5.6 Sol", "label": "GPT-5.6 Sol"}


def test_future_version_beats_previous_and_same_version_prefers_known_tier():
    assert web._best_available_model([
        {"label": "GPT-5.6 Sol", "disabled": False},
        {"label": "GPT-6 Astra", "disabled": False},
        {"label": "GPT-6 Pro", "disabled": False},
        {"label": "GPT-7 Luna", "disabled": True},
    ])["name"] == "GPT-6 Pro"


def test_unrecognized_enabled_option_and_rank_tie_fail_closed():
    with pytest.raises(web.ChatGPTWebModeError, match="unrecognized"):
        web._best_available_model([
            {"label": "GPT-5.6 Sol", "disabled": False},
            {"label": "New Revolutionary Model", "disabled": False},
        ])
    with pytest.raises(web.ChatGPTWebModeError, match="ambiguous"):
        web._best_available_model([
            {"label": "GPT-7 Alpha", "disabled": False},
            {"label": "GPT-7 Beta", "disabled": False},
        ])


def test_auto_mode_requires_selected_model_proof_even_when_high(monkeypatch):
    monkeypatch.setenv("UWA_CODEX_WEB_MODEL", "auto-best")
    monkeypatch.setattr(policy, "temporary_chat_strict", lambda: False)
    missing = policy.evaluate_codex_web_state(
        {"model": None, "resolved_model": "GPT-6 Pro", "reasoning": "high",
         "reasoning_slider": {"min": 0, "max": 2, "now": 2}}, "max"
    )
    assert not missing["verified"]
    assert not missing["model_verified"]
    good = policy.evaluate_codex_web_state(
        {"model": "GPT-6 Pro", "resolved_model": "GPT-6 Pro", "reasoning": None,
         "reasoning_slider": {"min": 0, "max": 3, "now": 3}}, "max"
    )
    assert good["verified"]
    assert good["model_verification"] == "dom"
    too_low = policy.evaluate_codex_web_state(
        {"model": "GPT-6 Pro", "resolved_model": "GPT-6 Pro",
         "reasoning_slider": {"min": 0, "max": 3, "now": 2}}, "max"
    )
    assert not too_low["verified"]


def test_max_policy_applies_even_when_codex_requests_high(monkeypatch):
    monkeypatch.setenv("UWA_CODEX_REASONING_DEFAULT", "max")
    assert policy.normalize_codex_reasoning({"effort": "high"}) == "max"
    monkeypatch.setenv("UWA_CODEX_REASONING_DEFAULT", "high")
    assert policy.normalize_codex_reasoning({"effort": "medium"}) == "medium"


def test_slider_range_validation_is_generic(monkeypatch):
    monkeypatch.setattr(web, "_run_js", lambda _tab, script: {"min": 0, "max": 4, "now": 3}
                        if script == web._REASONING_DETAILS_JS else None)
    assert web._reasoning_details(object()) == {"min": 0, "max": 4, "now": 3}


def test_no_selection_from_only_disabled_radio():
    with pytest.raises(web.ChatGPTWebModeError, match="no selectable"):
        web._best_available_model([{"label": "GPT-8 Pro", "disabled": True}])


def test_english_retirement_prose_is_not_parsed_as_model_family():
    parts = web._model_parts("GPT-5.5 retires Oct 14")
    assert parts is not None
    assert parts[0] == "GPT-5.5"
    assert parts[2] == ""

    selected = web._best_available_model([
        {"label": "GPT-5.6 Sol", "disabled": False},
        {"label": "GPT-5.5 retires Oct 14", "disabled": False},
    ])
    assert selected["name"] == "GPT-5.6 Sol"


def test_unknown_same_version_family_competitor_fails_closed():
    with pytest.raises(web.ChatGPTWebModeError, match="ambiguous"):
        web._best_available_model([
            {"label": "GPT-6 Pro", "disabled": False},
            {"label": "GPT-6 Ultra", "disabled": False},
        ])

    selected = web._best_available_model([
        {"label": "GPT-6 Pro", "disabled": False},
        {"label": "GPT-7 Ultra", "disabled": False},
    ])
    assert selected["name"] == "GPT-7 Ultra"


def test_temporary_chat_probe_does_not_open_model_picker(monkeypatch):
    monkeypatch.setattr(web, "temporary_chat_enabled", lambda: True)
    monkeypatch.setattr(
        web,
        "_run_js",
        lambda _tab, script, *_args: {
            "model": None,
            "reasoning": None,
            "temporary_chat": True,
        } if script == web._STATE_JS else (_ for _ in ()).throw(
            AssertionError("unexpected model-picker probe")
        ),
    )
    monkeypatch.setattr(
        web,
        "inspect_chatgpt_web_mode",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("full inspector should not run")
        ),
    )

    web._ensure_temporary_chat(object())
