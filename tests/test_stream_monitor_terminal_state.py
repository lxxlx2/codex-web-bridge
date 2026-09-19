from app.core.stream_monitor import _ordinary_text_completion_reason


def _reason(**overrides):
    values = {
        "content_ever_changed": True,
        "suppress_fast_exit": False,
        "still_generating": False,
        "stable_text_count": 6,
        "stable_count_threshold": 6,
        "silence_duration": 6.0,
        "silence_threshold": 5.0,
        "silence_threshold_fallback": 5.0,
    }
    values.update(overrides)
    return _ordinary_text_completion_reason(**values)


def test_stable_text_does_not_complete_while_generation_is_active():
    assert _reason(still_generating=True) == ""


def test_stable_text_completes_after_generation_becomes_idle():
    assert _reason(still_generating=False) == "stable"


def test_long_silence_does_not_complete_while_generation_is_active():
    assert _reason(
        still_generating=True,
        stable_text_count=0,
        silence_duration=16.0,
    ) == ""


def test_long_silence_completes_after_generation_becomes_idle():
    assert _reason(
        still_generating=False,
        stable_text_count=0,
        silence_duration=16.0,
    ) == "long_silence"


def test_ordinary_text_helper_does_not_claim_non_text_path():
    assert _reason(
        content_ever_changed=False,
        still_generating=False,
        silence_duration=60.0,
    ) == ""


def test_suppressed_fast_exit_remains_non_terminal():
    assert _reason(
        suppress_fast_exit=True,
        still_generating=False,
        silence_duration=60.0,
    ) == ""
