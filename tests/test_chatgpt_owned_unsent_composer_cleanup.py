
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

class _Tab:
    def __init__(self, url: str):
        self.url = url


def test_chatgpt_pre_fill_guard_waits_before_mutating_composer(monkeypatch):
    executor = WorkflowExecutor.__new__(WorkflowExecutor)
    executor.tab = _Tab("https://chatgpt.com/c/test")
    executor._selectors = {
        "send_btn": 'css:[data-testid="send-button"]',
    }

    seen = []

    def wait(selector, *, wait_timeout_override=None):
        seen.append((selector, wait_timeout_override))
        return True

    executor._wait_for_send_idle_before_action = wait
    monkeypatch.setenv(
        "UWA_CHATGPT_PRE_FILL_IDLE_TIMEOUT_SEC",
        "300",
    )

    assert executor._wait_for_chatgpt_idle_before_fill(
        "input_box"
    ) is True
    assert seen == [
        ('css:[data-testid="send-button"]', 300.0),
    ]


def test_non_chatgpt_pre_fill_guard_is_noop(monkeypatch):
    executor = WorkflowExecutor.__new__(WorkflowExecutor)
    executor.tab = _Tab("https://example.com/")
    executor._selectors = {}
    called = []

    executor._wait_for_send_idle_before_action = (
        lambda *args, **kwargs: called.append(
            (args, kwargs)
        )
        or True
    )
    monkeypatch.setenv(
        "UWA_CHATGPT_PRE_FILL_IDLE_TIMEOUT_SEC",
        "300",
    )

    assert executor._wait_for_chatgpt_idle_before_fill(
        "input_box"
    ) is True
    assert called == []


def test_fill_input_runs_idle_guard_before_actual_fill():
    executor = WorkflowExecutor.__new__(WorkflowExecutor)
    executor._should_stop = lambda: False
    executor._current_step_execution = {}
    executor._last_stream_media_state = {}

    events = []

    executor._stage_request_transport_from_context = (
        lambda **kwargs: False
    )
    executor._wait_for_chatgpt_idle_before_fill = (
        lambda target_key: events.append(
            ("idle", target_key)
        )
        or True
    )
    executor._execute_fill = (
        lambda selector, prompt, target_key, optional:
        events.append(
            (
                "fill",
                selector,
                prompt,
                target_key,
                optional,
            )
        )
    )

    list(
        executor.execute_step(
            "FILL_INPUT",
            "css:#prompt",
            "input_box",
            optional=False,
            context={"prompt": "next prompt"},
        )
    )

    assert events == [
        ("idle", "input_box"),
        (
            "fill",
            "css:#prompt",
            "next prompt",
            "input_box",
            False,
        ),
    ]


def test_request_transport_fill_path_skips_browser_idle_guard():
    executor = WorkflowExecutor.__new__(WorkflowExecutor)
    executor._should_stop = lambda: False
    executor._current_step_execution = {}
    executor._last_stream_media_state = {}

    events = []

    executor._stage_request_transport_from_context = (
        lambda **kwargs: True
    )
    executor._wait_for_chatgpt_idle_before_fill = (
        lambda target_key: events.append(
            ("idle", target_key)
        )
        or True
    )
    executor._execute_fill = (
        lambda *args, **kwargs: events.append(
            ("fill", args, kwargs)
        )
    )

    list(
        executor.execute_step(
            "FILL_INPUT",
            "css:#prompt",
            "input_box",
            optional=False,
            context={"prompt": "transport prompt"},
        )
    )

    assert events == []

