"""Prepare a fresh ChatGPT composer for Codex web-mode verification.

The web-mode controls can be absent while an existing ``/c/...`` conversation
is open.  This helper performs the narrow navigation needed before model/mode
verification: when the controlled tab is on an existing conversation, click
ChatGPT's new-chat control and wait for a fresh composer.

Security boundary: this module only inspects the current pathname and whether
the prompt editor is present.  It does not read conversation content, cookies,
local storage, account identifiers, or hidden application state.
"""

from __future__ import annotations

import time
from typing import Any, Dict

from app.services.chatgpt_web_mode import ChatGPTWebModeError, _find_chatgpt_tab


_PROBE_JS = r"""
return {
  pathname: String(location.pathname || ''),
  prompt: !!document.querySelector('#prompt-textarea') ||
          !!document.querySelector('[role="textbox"][aria-label*="ChatGPT"]') ||
          !!document.querySelector('[contenteditable="true"][role="textbox"]'),
};
"""


_NEW_CHAT_JS = r"""
const visible = (el) => {
  if (!el) return false;
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  return !!style && style.display !== 'none' && style.visibility !== 'hidden' &&
    rect.width > 0 && rect.height > 0;
};
const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();

const preferred = document.querySelector('[data-testid="create-new-chat-button"]');
let target = preferred && visible(preferred) ? preferred : null;

if (!target) {
  const exact = new Set(['新聊天', '新对话', 'new chat']);
  target = Array.from(document.querySelectorAll('a,button,[role="button"]'))
    .filter(visible)
    .find((el) => {
      const text = norm(el.innerText || el.textContent);
      const aria = norm(el.getAttribute('aria-label'));
      return exact.has(text) || exact.has(aria);
    }) || null;
}

if (!target) {
  return {clicked: false, pathname: String(location.pathname || '')};
}

target.click();
return {clicked: true, pathname: String(location.pathname || '')};
"""


def _run_js(tab: Any, script: str) -> Dict[str, Any]:
    try:
        result = tab.run_js(script)
    except Exception as exc:
        raise ChatGPTWebModeError(f"fresh-composer browser JavaScript failed: {exc}") from exc
    return result if isinstance(result, dict) else {}


def _probe(tab: Any) -> Dict[str, Any]:
    state = _run_js(tab, _PROBE_JS)
    return {
        "pathname": str(state.get("pathname") or ""),
        "prompt": bool(state.get("prompt")),
    }


def _is_existing_conversation(pathname: str) -> bool:
    return str(pathname or "").startswith("/c/")


def prepare_chatgpt_fresh_composer(*, timeout_seconds: float = 5.0) -> Dict[str, Any]:
    """Ensure the controlled ChatGPT tab is on a fresh, usable composer."""
    tab = _find_chatgpt_tab()
    before = _probe(tab)

    if not _is_existing_conversation(before["pathname"]):
        if not before["prompt"]:
            raise ChatGPTWebModeError(
                f"fresh ChatGPT page has no usable prompt editor: pathname={before['pathname']!r}"
            )
        return {
            "prepared": True,
            "opened_new_chat": False,
            "pathname": before["pathname"],
        }

    click_result = _run_js(tab, _NEW_CHAT_JS)
    if not click_result.get("clicked"):
        raise ChatGPTWebModeError(
            "existing ChatGPT conversation is open but the safe new-chat control was not found"
        )

    deadline = time.monotonic() + max(0.5, float(timeout_seconds))
    last = before
    while time.monotonic() < deadline:
        time.sleep(0.12)
        last = _probe(tab)
        if last["prompt"] and not _is_existing_conversation(last["pathname"]):
            return {
                "prepared": True,
                "opened_new_chat": True,
                "pathname": last["pathname"],
            }

    raise ChatGPTWebModeError(
        "new-chat navigation did not reach a fresh ChatGPT composer "
        f"within {timeout_seconds:.1f}s: pathname={last['pathname']!r}, prompt={last['prompt']}"
    )
