#!/usr/bin/env python3
"""Acceptance-only ChatGPT Web surface normalization and readiness probe.

This tool is intentionally narrow: it may select one exact Chat control from a
controlled Work/ambiguous ChatGPT surface and may navigate an existing Chat
conversation to New Chat. It never sends messages, clears composer text,
changes accounts, or bypasses quota/rate limits.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.chatgpt_web_prepare import (  # noqa: E402
    ChatGPTWebModeError,
    prepare_chatgpt_fresh_composer,
)
from app.services.chatgpt_web_surface import (  # noqa: E402
    controlled_chatgpt_tabs,
    inspect_chatgpt_surface,
)


_SWITCH_CHAT_JS = r"""
const visible = (el) => {
  if (!el) return false;
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  return !!style && style.display !== 'none' && style.visibility !== 'hidden' &&
    rect.width > 0 && rect.height > 0;
};
const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
const exact = new Set(['chat', '聊天']);
const matches = Array.from(document.querySelectorAll(
  'button,a,[role="tab"],[role="button"]'
)).filter(visible).filter((el) => {
  const text = norm(el.innerText || el.textContent);
  const aria = norm(el.getAttribute('aria-label'));
  return exact.has(text) || exact.has(aria);
});
if (matches.length !== 1) return {clicked: false, matches: matches.length};
matches[0].click();
return {clicked: true, matches: 1};
"""


def _emit(payload: dict[str, Any]) -> None:
    print(
        "SURFACE_PREFLIGHT_JSON="
        + json.dumps(payload, ensure_ascii=False, sort_keys=True),
        flush=True,
    )


def _can_safely_select_chat(state: Any) -> bool:
    return bool(
        state.blocking_reason in {"work_surface", "unknown_surface"}
        and state.prompt_present
        and state.composer_empty
    )


def _wait_initial_surface(tab: Any, timeout_seconds: float) -> Any:
    """Allow a newly-created ChatGPT target to finish rendering before classifying it.

    ChatGPT can render the composer before the mode chrome/badge appears.  In
    that window a restored draft can look like an ordinary Chat dirty composer
    even though the fully-rendered page is Work.  Keep sampling a bounded number
    of times when that exact provisional state appears so acceptance does not
    freeze the classification too early.
    """
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    state = inspect_chatgpt_surface(tab, target_count=1)
    transient = {"unknown_surface", "prompt_missing", "send_missing"}
    dirty_settle_samples = 0
    max_dirty_settle_samples = 12

    while time.monotonic() < deadline:
        if state.blocking_reason == "composer_not_empty":
            dirty_settle_samples += 1
            if dirty_settle_samples >= max_dirty_settle_samples:
                break
            time.sleep(0.15)
            state = inspect_chatgpt_surface(tab, target_count=1)
            continue

        if state.blocking_reason not in transient:
            break
        if state.prompt_present and state.composer_empty:
            # An ambiguous rendered surface may already be safe to normalize
            # through the exact Chat control; do not wait the whole timeout.
            break
        time.sleep(0.15)
        state = inspect_chatgpt_surface(tab, target_count=1)
    return state


def run(*, timeout_seconds: float = 8.0) -> int:
    actions: list[str] = []
    tabs = controlled_chatgpt_tabs()
    if len(tabs) != 1:
        _emit(
            {
                "ok": False,
                "failure_class": (
                    "chatgpt_target_missing"
                    if not tabs
                    else "chatgpt_target_ambiguous"
                ),
                "target_count": len(tabs),
                "actions": actions,
            }
        )
        return 1

    tab = tabs[0]
    state = _wait_initial_surface(tab, timeout_seconds)

    # Acceptance owns this disposable target. If Chat/Work controls are visible
    # but selection semantics are absent, selecting one exact Chat control is a
    # safe normalization action only while the composer is empty. Normal runtime
    # remains fail-closed and never performs this switch automatically.
    if _can_safely_select_chat(state):
        original_reason = state.blocking_reason
        result = tab.run_js(_SWITCH_CHAT_JS)
        if not isinstance(result, dict) or not result.get("clicked"):
            _emit(
                {
                    "ok": False,
                    "failure_class": _failure_class(original_reason),
                    "target_count": 1,
                    "surface_kind": state.surface_kind,
                    "blocking_reason": original_reason,
                    "actions": actions,
                }
            )
            return 1
        actions.append("switch_to_chat")
        deadline = time.monotonic() + max(1.0, float(timeout_seconds))
        while time.monotonic() < deadline:
            time.sleep(0.15)
            state = inspect_chatgpt_surface(tab, target_count=1)
            if state.surface_kind == "chat" and state.blocking_reason in {
                "none",
                "composer_not_empty",
            }:
                break

    if state.blocking_reason not in {"none", "composer_not_empty"}:
        _emit(
            {
                "ok": False,
                "failure_class": _failure_class(state.blocking_reason),
                "target_count": 1,
                "surface_kind": state.surface_kind,
                "blocking_reason": state.blocking_reason,
                "actions": actions,
            }
        )
        return 1

    if not state.composer_empty:
        _emit(
            {
                "ok": False,
                "failure_class": "chatgpt_composer_not_empty",
                "target_count": 1,
                "surface_kind": state.surface_kind,
                "blocking_reason": "composer_not_empty",
                "actions": actions,
            }
        )
        return 1

    if state.pathname_class == "conversation":
        try:
            preparation = prepare_chatgpt_fresh_composer(
                timeout_seconds=timeout_seconds
            )
        except ChatGPTWebModeError:
            _emit(
                {
                    "ok": False,
                    "failure_class": "chatgpt_surface_prepare_failed",
                    "target_count": 1,
                    "actions": actions,
                }
            )
            return 1
        if preparation.get("opened_new_chat"):
            actions.append("new_chat")
        tabs = controlled_chatgpt_tabs()
        if len(tabs) != 1:
            _emit(
                {
                    "ok": False,
                    "failure_class": "chatgpt_target_ambiguous",
                    "target_count": len(tabs),
                    "actions": actions,
                }
            )
            return 1
        tab = tabs[0]
        state = inspect_chatgpt_surface(tab, target_count=1)

    if not state.surface_ready:
        _emit(
            {
                "ok": False,
                "failure_class": _failure_class(state.blocking_reason),
                "target_count": 1,
                "surface_kind": state.surface_kind,
                "pathname_class": state.pathname_class,
                "composer_empty": state.composer_empty,
                "blocking_reason": state.blocking_reason,
                "actions": actions,
            }
        )
        return 1

    _emit(
        {
            "ok": True,
            "failure_class": "none",
            "target_count": 1,
            "surface_kind": state.surface_kind,
            "pathname_class": state.pathname_class,
            "composer_empty": state.composer_empty,
            "blocking_reason": state.blocking_reason,
            "actions": actions,
        }
    )
    return 0


def _failure_class(reason: str) -> str:
    return {
        "target_missing": "chatgpt_target_missing",
        "target_ambiguous": "chatgpt_target_ambiguous",
        "work_surface": "chatgpt_work_surface",
        "composer_not_empty": "chatgpt_composer_not_empty",
        "work_quota_exhausted": "chatgpt_work_quota_exhausted",
        "usage_exhausted": "chatgpt_usage_exhausted",
        "rate_limited": "chatgpt_web_rate_limited",
        "auth_required": "chatgpt_auth_required",
        "challenge": "chatgpt_challenge",
        "unknown_surface": "chatgpt_surface_unknown",
        "prompt_missing": "chatgpt_surface_unknown",
        "send_missing": "chatgpt_surface_unknown",
    }.get(reason, "chatgpt_surface_prepare_failed")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-sec", type=float, default=8.0)
    args = parser.parse_args()
    return run(timeout_seconds=args.timeout_sec)


if __name__ == "__main__":
    raise SystemExit(main())
