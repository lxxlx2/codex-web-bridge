from __future__ import annotations

from app.services.chatgpt_web_surface import classify_surface_probe


def _probe(**overrides):
    base = {
        "host": "chatgpt.com",
        "pathname": "/",
        "prompt_present": True,
        "composer_chars": 0,
        "send_control_present": True,
        "selected_chat": True,
        "selected_work": False,
        "chat_control_present": True,
        "work_control_present": True,
        "work_quota_exhausted": False,
        "usage_exhausted": False,
        "rate_limited": False,
        "auth_required": False,
        "challenge_present": False,
    }
    base.update(overrides)
    return base


def test_chat_root_ready():
    state = classify_surface_probe(_probe())
    assert state.surface_kind == "chat"
    assert state.pathname_class == "root"
    assert state.composer_empty is True
    assert state.surface_ready is True
    assert state.blocking_reason == "none"


def test_chat_existing_conversation_is_classified_without_leaking_id():
    state = classify_surface_probe(_probe(pathname="/c/private-conversation-id"))
    assert state.pathname_class == "conversation"
    assert state.surface_ready is True
    assert "private" not in str(state.to_dict())


def test_work_selected_blocks():
    state = classify_surface_probe(
        _probe(selected_chat=False, selected_work=True)
    )
    assert state.surface_kind == "work"
    assert state.surface_ready is False
    assert state.blocking_reason == "work_surface"


def test_conflicting_chat_and_work_evidence_fails_closed():
    state = classify_surface_probe(_probe(selected_chat=True, selected_work=True))
    assert state.surface_kind == "unknown"
    assert state.blocking_reason == "unknown_surface"


def test_visible_chat_and_work_without_selected_evidence_fails_closed():
    state = classify_surface_probe(
        _probe(selected_chat=False, selected_work=False)
    )
    assert state.surface_kind == "unknown"
    assert state.surface_ready is False
    assert state.blocking_reason == "unknown_surface"


def test_prompt_only_layout_can_be_inferred_as_chat():
    state = classify_surface_probe(
        _probe(
            selected_chat=False,
            selected_work=False,
            chat_control_present=False,
            work_control_present=False,
        )
    )
    assert state.surface_kind == "chat"
    assert state.surface_ready is True


def test_quota_and_transport_blockers_have_stable_precedence():
    cases = [
        ({"rate_limited": True}, "rate_limited"),
        ({"work_quota_exhausted": True}, "work_quota_exhausted"),
        ({"usage_exhausted": True}, "usage_exhausted"),
        ({"auth_required": True}, "auth_required"),
        ({"challenge_present": True}, "challenge"),
    ]
    for updates, expected in cases:
        state = classify_surface_probe(_probe(**updates))
        assert state.surface_ready is False
        assert state.blocking_reason == expected


def test_dirty_composer_blocks_without_returning_text():
    state = classify_surface_probe(_probe(composer_chars=42))
    payload = state.to_dict()
    assert state.surface_ready is False
    assert state.blocking_reason == "composer_not_empty"
    assert payload["composer_chars"] == 42
    assert "composer_text" not in payload


def test_missing_prompt_or_send_control_blocks():
    no_prompt = classify_surface_probe(
        _probe(prompt_present=False, send_control_present=False)
    )
    assert no_prompt.blocking_reason in {"unknown_surface", "prompt_missing"}

    no_send = classify_surface_probe(_probe(send_control_present=False))
    assert no_send.blocking_reason == "send_missing"


def test_target_missing_and_ambiguous_fail_before_page_state():
    missing = classify_surface_probe({}, target_count=0)
    assert missing.blocking_reason == "target_missing"
    assert missing.surface_ready is False

    ambiguous = classify_surface_probe(_probe(), target_count=2)
    assert ambiguous.blocking_reason == "target_ambiguous"
    assert ambiguous.surface_ready is False


def test_non_chatgpt_host_fails_closed():
    state = classify_surface_probe(_probe(host="example.com"))
    assert state.host_ok is False
    assert state.blocking_reason == "unknown_surface"
