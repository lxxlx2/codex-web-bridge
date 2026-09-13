#!/usr/bin/env python3
"""Acceptance-only ChatGPT Web surface normalization and readiness probe.

This tool is intentionally narrow: it may switch one controlled Work surface to
Chat and may navigate an existing Chat conversation to New Chat. It never sends
messages, clears composer text, changes accounts, or bypasses quota/rate limits.
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
    print("SURFACE_PREFLIGHT_JSON=" + json.dumps(payload, ensure_ascii=False, sort_keys=True))


def run(*, timeout_seconds: float = 8.0) -> int:
    actions: list[str] = []
    tabs = controlled_chatgpt_tabs()
    if len(tabs) != 1:
        _emit(
            {
                "ok": False,
                "failure_class": "chatgpt_target_missing" if not tabs else "chatgpt_target_ambiguous",
                "target_count": len(tabs),
                "actions": actions,
            }
        )
        return 1

    tab = tabs[0]
    state = inspect_chatgpt_surface(tab, target_count=1)

    if state.blocking_reason == "work_surface":
        result = tab.run_js(_SWITCH_CHAT_JS)
        if not isinstance(result, dict) or not result.get("clicked"):
            _emit(
                {
                    "ok": False,
                    "failure_class": "chatgpt_work_surface",
                    "target_count": 1,
                    "surface_kind": state.surface_kind,
                    "blocking_reason": state.blocking_reason,
                    "actions": actions,
                }
            )
            return 1
        actions.append("switch_to_chat")
        deadline = time.monotonic() + max(1.0, float(timeout_seconds))
        while time.monotonic() < deadline:
            time.sleep(0.15)
            state = inspect_chatgpt_surface(tab, target_count=1)
            if state.surface_kind == "chat":
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
            preparation = prepare_chatgpt_fresh_composer(timeout_seconds=timeout_seconds)
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
