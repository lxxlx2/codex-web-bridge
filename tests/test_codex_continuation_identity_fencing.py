from app.services import codex_v2_runtime_hardening as runtime
from app.services import codex_web_session_affinity as affinity


def _clear_runtime_call_ids():
    with runtime._CALL_RESPONSE_LOCK:
        runtime._CALL_RESPONSE_IDS.clear()


def _clear_affinity_bindings():
    with affinity._BINDINGS_LOCK:
        affinity._BINDINGS.clear()


def test_call_id_identity_is_stable_for_identical_replay():
    _clear_runtime_call_ids()

    runtime._remember_call_response(["call_stable"], "resp_one")
    assert runtime._resolve_call_response(["call_stable"]) == "resp_one"

    runtime._remember_call_response(["call_stable"], "resp_one")
    assert runtime._resolve_call_response(["call_stable"]) == "resp_one"


def test_conflicting_call_id_response_is_fenced_fail_closed():
    _clear_runtime_call_ids()

    runtime._remember_call_response(["call_conflict"], "resp_old")
    assert runtime._resolve_call_response(["call_conflict"]) == "resp_old"

    runtime._remember_call_response(["call_conflict"], "resp_late_other")
    assert runtime._resolve_call_response(["call_conflict"]) == ""

    runtime._remember_call_response(["call_conflict"], "resp_old")
    assert runtime._resolve_call_response(["call_conflict"]) == ""


def test_one_conflicted_call_id_fences_multi_output_affinity_resolution():
    _clear_runtime_call_ids()

    runtime._remember_call_response(["call_good"], "resp_good")
    runtime._remember_call_response(["call_bad"], "resp_old")
    runtime._remember_call_response(["call_bad"], "resp_other")

    assert runtime._resolve_call_response(["call_good", "call_bad"]) == ""
    assert runtime._resolve_call_response(["call_good"]) == "resp_good"


def test_response_affinity_identical_rebind_is_allowed(monkeypatch):
    _clear_affinity_bindings()
    monkeypatch.setenv("UWA_CODEX_WEB_SESSION_AFFINITY", "true")

    assert affinity.bind_response_to_conversation(
        "resp_stable",
        "/c/identity-stable-1234",
        model="GPT-5.6 Sol",
        reasoning="high",
    ) is True
    assert affinity.bind_response_to_conversation(
        "resp_stable",
        "/c/identity-stable-1234",
        model="gpt-5.6 sol",
        reasoning={"effort": "high"},
    ) is True

    resolved = affinity.resolve_conversation_binding(
        "resp_stable",
        model="GPT-5.6 Sol",
        reasoning="high",
    )
    assert resolved is not None
    assert resolved.pathname == "/c/identity-stable-1234"


def test_response_affinity_conflicting_path_is_rejected_without_overwrite(monkeypatch):
    _clear_affinity_bindings()
    monkeypatch.setenv("UWA_CODEX_WEB_SESSION_AFFINITY", "true")

    assert affinity.bind_response_to_conversation(
        "resp_locked",
        "/c/original-path-1234",
        model="GPT-5.6 Sol",
        reasoning="high",
    ) is True

    assert affinity.bind_response_to_conversation(
        "resp_locked",
        "/c/stale-other-path-5678",
        model="GPT-5.6 Sol",
        reasoning="high",
    ) is False

    resolved = affinity.resolve_conversation_binding(
        "resp_locked",
        model="GPT-5.6 Sol",
        reasoning="high",
    )
    assert resolved is not None
    assert resolved.pathname == "/c/original-path-1234"


def test_response_affinity_conflicting_model_or_reasoning_is_rejected(monkeypatch):
    _clear_affinity_bindings()
    monkeypatch.setenv("UWA_CODEX_WEB_SESSION_AFFINITY", "true")

    assert affinity.bind_response_to_conversation(
        "resp_policy",
        "/c/policy-path-12345678",
        model="GPT-5.6 Sol",
        reasoning="high",
    ) is True

    assert affinity.bind_response_to_conversation(
        "resp_policy",
        "/c/policy-path-12345678",
        model="Another Model",
        reasoning="high",
    ) is False
    assert affinity.bind_response_to_conversation(
        "resp_policy",
        "/c/policy-path-12345678",
        model="GPT-5.6 Sol",
        reasoning="medium",
    ) is False

    resolved = affinity.resolve_conversation_binding(
        "resp_policy",
        model="GPT-5.6 Sol",
        reasoning="high",
    )
    assert resolved is not None
    assert resolved.model == "gpt-5.6 sol"
    assert resolved.reasoning == "high"
