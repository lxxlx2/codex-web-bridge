import json

from app.core.generation_state import GENERATION_INDICATOR_CSS_SELECTORS
from app.core.stream_monitor import (
    GeneratingStatusCache,
    _final_settle_generation_transition,
    _ordinary_text_completion_reason,
)
from app.core.workflow.executor_send import WorkflowExecutorSendMixin


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


class _DisplayedStates:
    is_displayed = True


class _DisplayedElement:
    states = _DisplayedStates()


class _SelectorOnlyTab:
    def __init__(self, selector):
        self.selector = selector
        self.calls = []

    def ele(self, selector, timeout=0):
        self.calls.append((selector, timeout))
        if selector == self.selector:
            return _DisplayedElement()
        return None


def test_shared_generation_selectors_cover_localized_chatgpt_stop_controls():
    assert 'button[aria-label*="停止"]' in GENERATION_INDICATOR_CSS_SELECTORS
    assert '[data-testid="stop-button"]' in GENERATION_INDICATOR_CSS_SELECTORS


def test_stream_generation_cache_detects_chinese_stop_control():
    tab = _SelectorOnlyTab('css:button[aria-label*="停止"]')
    cache = GeneratingStatusCache(tab)

    assert cache.is_generating() is True
    assert _reason(still_generating=cache.is_generating()) == ""


def test_stream_generation_cache_detects_chatgpt_stop_testid():
    tab = _SelectorOnlyTab('css:[data-testid="stop-button"]')
    cache = GeneratingStatusCache(tab)

    assert cache.is_generating() is True


class _ComposerStopRunJsTab:
    def __init__(self):
        self.js = ""

    def ele(self, selector, timeout=0):
        return None

    def run_js(self, js):
        self.js = js
        return True


def test_stream_generation_cache_detects_composer_stop_metadata_fallback():
    tab = _ComposerStopRunJsTab()
    cache = GeneratingStatusCache(tab)

    assert cache.is_generating() is True
    assert "#prompt-textarea" in tab.js
    assert "stopping" in tab.js
    assert "停止" in tab.js


def test_final_settle_generation_reappearance_resets_stability_window():
    active_since, reset = _final_settle_generation_transition(
        was_generating=False,
        still_generating=True,
        active_since=None,
        now=10.0,
    )
    assert active_since == 10.0
    assert reset is True

    active_since, reset = _final_settle_generation_transition(
        was_generating=True,
        still_generating=True,
        active_since=10.0,
        now=11.0,
    )
    assert active_since == 10.0
    assert reset is True

    active_since, reset = _final_settle_generation_transition(
        was_generating=True,
        still_generating=False,
        active_since=10.0,
        now=12.0,
    )
    assert active_since is None
    assert reset is True

    active_since, reset = _final_settle_generation_transition(
        was_generating=False,
        still_generating=False,
        active_since=None,
        now=13.0,
    )
    assert active_since is None
    assert reset is False


class _RunJsCaptureTab:
    def __init__(self):
        self.js = ""

    def run_js(self, js):
        self.js = js
        return {
            "ok": True,
            "sendFound": True,
            "sendDisabled": False,
            "sendLooksLikeStop": False,
            "stopBtnFound": False,
            "configuredGenFound": False,
            "matchedIndicatorSelector": "",
            "generating": False,
            "details": [],
            "visibleButtons": [],
        }


class _SendProbeHarness(WorkflowExecutorSendMixin):
    def __init__(self, tab):
        self.tab = tab
        self._selectors = {
            "send_btn": '[data-testid="send-button"]',
            "generating_indicator": None,
            "stop_btn": None,
        }


def test_pre_send_probe_uses_same_localized_generation_selectors():
    tab = _RunJsCaptureTab()
    harness = _SendProbeHarness(tab)

    harness._probe_send_post_click_state('[data-testid="send-button"]')

    expected = json.dumps(
        list(GENERATION_INDICATOR_CSS_SELECTORS),
        ensure_ascii=False,
    )
    assert f"const sharedGenerationSelectors = {expected};" in tab.js
