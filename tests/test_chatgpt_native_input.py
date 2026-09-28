import pytest

from app.core.config import WorkflowError
from app.core.workflow.text_input import TextInputHandler


class _Editor:
    def __init__(self, *, chatgpt=True):
        self.chatgpt = chatgpt
        self.blurred = False

    def run_js(self, script):
        if "this.matches" in script:
            return self.chatgpt
        if "this.blur()" in script:
            self.blurred = True
            return True
        raise AssertionError("unexpected editor script")

    def click(self):
        return None


class _Tab:
    def __init__(self):
        self.text = ""
        self.chunks = []
        self.drop_input = False
        self.editor = None
        self.focus_count = 0
        self.clear_count = 0

    def run_js(self, script):
        if "execCommand('delete')" in script:
            self.clear_count += 1
            self.text = ""
            return True
        if "const paragraphs = Array.from(editor.children)" in script:
            return self.text
        assert "range.collapse(false)" in script
        self.focus_count += 1
        return True

    def ele(self, selector, timeout):
        assert '[role="textbox"]' in selector
        assert timeout == 0.5
        return self.editor

    def run_cdp(self, method, *, text):
        assert method == "Input.insertText"
        self.chunks.append(text)
        if not self.drop_input:
            self.text += text
        return {}


def _handler(tab):
    handler = TextInputHandler(tab, False, lambda *_args: None, lambda: False)
    handler.clear_input_safely = lambda _editor: setattr(tab, "text", "")
    handler.read_input_full_text = lambda _editor: tab.text
    return handler


def test_chatgpt_editor_uses_native_chunks_and_verifies_after_blur():
    tab = _Tab()
    editor = _Editor()
    tab.editor = editor
    handler = _handler(tab)
    handler.chunked_input = lambda *_args, **_kwargs: pytest.fail("DOM input fallback used")
    payload = "alpha\nbeta" + "x" * 2400

    handler.fill_via_js(editor, payload)

    assert editor.blurred is True
    assert tab.text == payload
    assert [len(chunk) for chunk in tab.chunks] == [1000, 1000, 410]
    assert tab.focus_count == 3
    assert tab.clear_count == 1


def test_chatgpt_editor_rejects_uncommitted_native_input():
    tab = _Tab()
    tab.drop_input = True
    handler = _handler(tab)
    tab.editor = _Editor()

    with pytest.raises(WorkflowError, match="input_mismatch"):
        handler._fill_chatgpt_editor_via_native_input(tab.editor, "must appear")


def test_chatgpt_editor_rejects_whitespace_drift():
    class _WhitespaceDriftTab(_Tab):
        def run_cdp(self, method, *, text):
            super().run_cdp(method, text=text)
            self.text = self.text.replace(" ", "", 1)

    tab = _WhitespaceDriftTab()
    handler = _handler(tab)
    tab.editor = _Editor()

    with pytest.raises(WorkflowError, match="input_mismatch"):
        handler._fill_chatgpt_editor_via_native_input(tab.editor, "foo bar")


def test_other_editors_do_not_use_chatgpt_native_input():
    tab = _Tab()
    handler = _handler(tab)

    assert handler._fill_chatgpt_editor_via_native_input(_Editor(chatgpt=False), "hello") is False
    assert tab.chunks == []
