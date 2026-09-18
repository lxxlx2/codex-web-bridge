
from __future__ import annotations

from app.core.workflow.executor import WorkflowExecutor


class _Element:
    def __init__(self, text: str):
        self.text = text


class _TextHandler:
    def normalize_for_compare(self, text: str) -> str:
        return str(text or "").replace("\\r\\n", "\\n").replace("\\r", "\\n").strip()

    def read_input_full_text(self, element: _Element) -> str:
        return element.text

    def clear_input_safely(self, element: _Element) -> None:
        element.text = ""


def _executor_with_fill(text: str):
    executor = WorkflowExecutor.__new__(WorkflowExecutor)
    executor._text_handler = _TextHandler()
    executor._last_input_element = _Element(text)
    executor._context = {}
    executor._resolve_active_text_input = lambda: None

    executor._last_fill_completed_at = 0.0
    executor._last_fill_text_length = 0
    executor._last_fill_text_sha256 = ""
    executor._last_fill_after_new_chat = False
    executor._last_send_dispatched_since_fill = False

    executor._note_fill_completion(text)
    return executor, executor._last_input_element


def test_owned_unsent_composer_is_cleared():
    executor, element = _executor_with_fill("owned prompt")

    assert executor._clear_owned_unsent_composer() is True
    assert element.text == ""
    assert executor._last_fill_text_length == 0
    assert executor._last_fill_text_sha256 == ""


def test_changed_composer_is_never_cleared():
    executor, element = _executor_with_fill("owned prompt")
    element.text = "user changed this text"

    assert executor._clear_owned_unsent_composer() is False
    assert element.text == "user changed this text"


def test_dispatched_send_is_never_rolled_back():
    executor, element = _executor_with_fill("owned prompt")
    executor._require_send_action_dispatched(True)

    assert executor._last_send_dispatched_since_fill is True
    assert executor._clear_owned_unsent_composer() is False
    assert element.text == "owned prompt"


def test_attachment_composer_is_never_auto_cleared():
    executor, element = _executor_with_fill("owned prompt")
    executor._context = {"images": ["image"]}

    assert executor._clear_owned_unsent_composer() is False
    assert element.text == "owned prompt"

def _prepare_cleanup_executor(executor):
    executor._cleanup_workflow_scripts = lambda: None
    executor._attachment_monitor = None
    executor._network_monitor = None
    executor._stream_monitor = None


def test_workflow_teardown_clears_owned_unsent_composer():
    executor, element = _executor_with_fill("cancelled helper prompt")
    _prepare_cleanup_executor(executor)

    executor.cleanup_after_workflow()

    assert element.text == ""
    assert executor._last_fill_text_length == 0
    assert executor._last_fill_text_sha256 == ""


def test_workflow_teardown_preserves_composer_after_real_dispatch():
    executor, element = _executor_with_fill("sent prompt")
    _prepare_cleanup_executor(executor)
    executor._require_send_action_dispatched(True)

    executor.cleanup_after_workflow()

    assert element.text == "sent prompt"
    assert executor._last_send_dispatched_since_fill is True

