"""Prepare a fresh, safe ChatGPT composer for Codex web-mode verification.

Fresh-flow preparation is intentionally conservative.  It may navigate from an
existing ChatGPT conversation to New Chat, but it never clears unknown composer
text, switches out of Work mode, dismisses quota/auth challenges, or reads
conversation content.  Acceptance-only surface normalization lives in the S3
runner.
"""

from __future__ import annotations

import time
from typing import Any, Dict

from app.services.chatgpt_web_mode import ChatGPTWebModeError, _find_chatgpt_tab
from app.services.chatgpt_web_surface import SurfaceSnapshot, inspect_chatgpt_surface


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
  const matches = Array.from(document.querySelectorAll('a,button,[role="button"]'))
    .filter(visible)
    .filter((el) => {
      const text = norm(el.innerText || el.textContent);
      const aria = norm(el.getAttribute('aria-label'));
      return exact.has(text) || exact.has(aria);
    });
  target = matches.length === 1 ? matches[0] : null;
}

if (!target) {
  return {clicked: false};
}

target.click();
return {clicked: true};
"""


def _run_js(tab: Any, script: str) -> Dict[str, Any]:
    try:
        result = tab.run_js(script)
    except Exception as exc:
        raise ChatGPTWebModeError(
            f"fresh-composer browser JavaScript failed: {exc}"
        ) from exc
    return result if isinstance(result, dict) else {}


def _snapshot(tab: Any) -> SurfaceSnapshot:
    return inspect_chatgpt_surface(tab, target_count=1)


def _raise_blocked(state: SurfaceSnapshot) -> None:
    reason = state.blocking_reason
    mapping = {
        "work_surface": "chatgpt_web_work_surface",
        "work_quota_exhausted": "chatgpt_web_work_quota_exhausted",
        "usage_exhausted": "chatgpt_web_usage_exhausted",
        "rate_limited": "chatgpt_web_rate_limited",
        "auth_required": "chatgpt_web_auth_required",
        "challenge": "chatgpt_web_challenge",
        "composer_not_empty": "chatgpt_web_composer_not_empty",
        "target_missing": "chatgpt_target_missing",
        "target_ambiguous": "chatgpt_target_ambiguous",
        "prompt_missing": "chatgpt_web_prompt_missing",
        "send_missing": "chatgpt_web_send_missing",
        "unknown_surface": "chatgpt_web_surface_unknown",
    }
    code = mapping.get(reason, "chatgpt_web_surface_not_ready")
    raise ChatGPTWebModeError(f"{code}: blocking_reason={reason}")


def prepare_chatgpt_fresh_composer(*, timeout_seconds: float = 5.0) -> Dict[str, Any]:
    """Ensure fresh-flow uses an ordinary Chat surface with an empty composer."""
    tab = _find_chatgpt_tab()
    before = _snapshot(tab)

    if before.surface_kind != "chat":
        _raise_blocked(before)
    if before.blocking_reason != "none":
        _raise_blocked(before)

    if before.pathname_class != "conversation":
        return {
            "prepared": True,
            "opened_new_chat": False,
            "pathname_class": before.pathname_class,
            "surface_kind": before.surface_kind,
            "composer_empty": before.composer_empty,
        }

    click_result = _run_js(tab, _NEW_CHAT_JS)
    if not click_result.get("clicked"):
        raise ChatGPTWebModeError(
            "existing ChatGPT conversation is open but the safe new-chat control "
            "was not found uniquely"
        )

    deadline = time.monotonic() + max(0.5, float(timeout_seconds))
    last = before
    while time.monotonic() < deadline:
        time.sleep(0.12)
        last = _snapshot(tab)
        if (
            last.pathname_class != "conversation"
            and last.surface_kind == "chat"
            and last.surface_ready
        ):
            return {
                "prepared": True,
                "opened_new_chat": True,
                "pathname_class": last.pathname_class,
                "surface_kind": last.surface_kind,
                "composer_empty": last.composer_empty,
            }

    raise ChatGPTWebModeError(
        "new-chat navigation did not reach a safe fresh ChatGPT composer "
        f"within {timeout_seconds:.1f}s: "
        f"pathname_class={last.pathname_class!r}, "
        f"surface_kind={last.surface_kind!r}, "
        f"blocking_reason={last.blocking_reason!r}"
    )
