from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.core.config import WorkflowError
from app.core.workflow.executor_actions import WorkflowExecutorActionMixin


class _LengthProbe(WorkflowExecutorActionMixin):
    def __init__(self, selector):
        self._selectors = {"input_box": selector}
        self.seen_selector = None
        self.tab = self

    def run_js(self, script, selector):
        self.seen_selector = selector
        if selector.startswith("css:"):
            raise ValueError("not a native CSS selector")
        return 44010


def test_input_length_probe_uses_native_css_for_configured_selector():
    probe = _LengthProbe(
        'css:[role="textbox"][contenteditable="true"], #prompt-textarea'
    )

    assert probe._safe_get_input_len_by_key("input_box") == 44010
    assert probe.seen_selector == (
        '[role="textbox"][contenteditable="true"], #prompt-textarea'
    )


class _SendProbe(WorkflowExecutorActionMixin):
    def __init__(self):
        self._context = {"prompt": "required input"}
        self.finder = self
        self.clicked = False
        self.pressed_enter = False

    @contextmanager
    def _page_interaction_slot(self, action, target_key):
        yield True

    def _check_cancelled(self):
        return False

    def find_with_fallback(self, selector, target_key):
        return object()

    def _wait_for_element_interactable(self, element, selector, target_key):
        return element

    def _get_current_url_snapshot(self, label):
        return ""

    def _safe_get_input_len_by_key(self, target_key):
        return 0

    def _get_send_confirmation_check_timeout(self):
        return 0.1

    def _click_element_with_configured_mode(self, element, target_key, selector):
        self.clicked = True

    def _execute_keypress(self, key):
        self.pressed_enter = True


def test_send_does_not_click_or_press_enter_when_input_is_unverified():
    probe = _SendProbe()

    with pytest.raises(WorkflowError, match="send_input_unverified"):
        probe._execute_click('[data-testid="send-button"]', "send_btn", False)

    assert probe.clicked is False
    assert probe.pressed_enter is False


def test_send_rechecks_native_chatgpt_editor_before_click():
    probe = _SendProbe()
    probe._safe_get_input_len_by_key = lambda _key: len("required input")
    probe._text_handler = SimpleNamespace(
        _chatgpt_native_input_used=True,
        read_chatgpt_editor_canonical_text=lambda: "requiredinput",
    )

    with pytest.raises(WorkflowError, match="send_input_unverified"):
        probe._execute_click('[data-testid="send-button"]', "send_btn", False)

    assert probe.clicked is False
    assert probe.pressed_enter is False
