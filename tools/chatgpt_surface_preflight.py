#!/usr/bin/env python3
"""Acceptance-only ChatGPT Web surface normalization and readiness probe.

This tool is intentionally narrow: it may select one exact Chat control from a
controlled Work/ambiguous ChatGPT surface, dismiss one acknowledgement-only
stale rate-limit notice, and may navigate an existing Chat conversation to New
Chat. It never sends messages, clears composer text, changes accounts, clicks
Retry, or bypasses quota/rate limits.
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


_SWITCH_MARKER_ATTR = "data-uwa-acceptance-chat-target"
_SWITCH_MARKER_SELECTOR = f'[{_SWITCH_MARKER_ATTR}="1"]'

_RATE_LIMIT_ACK_MARKER_ATTR = "data-uwa-acceptance-rate-limit-ack"
_RATE_LIMIT_ACK_MARKER_SELECTOR = f'[{_RATE_LIMIT_ACK_MARKER_ATTR}="1"]'

_SWITCH_CHAT_JS = rf"""
const marker = '{_SWITCH_MARKER_ATTR}';
document.querySelectorAll(`[${{marker}}]`).forEach((el) => el.removeAttribute(marker));
const visible = (el) => {{
  if (!el) return false;
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  return !!style && style.display !== 'none' && style.visibility !== 'hidden' &&
    rect.width > 0 && rect.height > 0;
}};
const norm = (value) => String(value || '').replace(/[\s\u200b-\u200d\ufeff]+/g, ' ').trim().toLowerCase();
const exactChat = new Set(['chat', '聊天']);
const exactWork = new Set(['work', '工作']);
const exactValue = (el, values) => {{
  if (!el) return false;
  const text = norm(el.innerText || el.textContent);
  const aria = norm(el.getAttribute && el.getAttribute('aria-label'));
  return values.has(text) || values.has(aria);
}};
const mark = (el, payload) => {{
  if (!el) return Object.assign({{marked: false}}, payload);
  el.setAttribute(marker, '1');
  return Object.assign({{marked: true}}, payload);
}};

// Preferred path: one explicitly interactive Chat control. Mark it for a real
// browser-level click from DrissionPage instead of calling HTMLElement.click().
const interactive = Array.from(document.querySelectorAll(
  'button,a,[role="tab"],[role="button"],[aria-selected],[aria-pressed],'+
  '[data-state],[data-selected],[tabindex]'
)).filter(visible);
const interactiveMatches = interactive.filter((el) => exactValue(el, exactChat));
if (interactiveMatches.length === 1) {{
  return mark(interactiveMatches[0], {{
    strategy: 'interactive',
    interactive_matches: 1,
    paired_matches: 0,
    segment_matches: 1,
  }});
}}

// Current ChatGPT can render Chat/Work as a segmented selector with nested
// wrappers. Locate one exact Chat label paired with one exact Work label, derive
// the unique Chat-side branch inside their nearest common ancestor, then mark
// the nearest exact interactive ancestor around the Chat leaf for a real
// browser-level click. Marking the whole branch is insufficient on the current
// segmented control because its click handler lives on a nested interactive
// node. No coordinates or fuzzy text clicks are used.
const labelSelector = 'span,div,p,label';
const leafLabels = (values) => Array.from(document.querySelectorAll(labelSelector))
  .filter(visible)
  .filter((el) => exactValue(el, values))
  .filter((el) => !Array.from(el.querySelectorAll(labelSelector))
    .filter((child) => child !== el && visible(child))
    .some((child) => exactValue(child, values)));

const chatLabels = leafLabels(exactChat);
const workLabels = leafLabels(exactWork);
const pairs = [];
for (const chat of chatLabels) {{
  let ancestor = chat.parentElement;
  for (let depth = 0; ancestor && ancestor !== document.body && depth < 6; depth += 1) {{
    const chatsHere = chatLabels.filter((el) => ancestor.contains(el));
    const worksHere = workLabels.filter((el) => ancestor.contains(el));
    if (chatsHere.length === 1 && worksHere.length === 1) {{
      pairs.push({{chat, work: worksHere[0], ancestor}});
      break;
    }}
    ancestor = ancestor.parentElement;
  }}
}}

const uniquePairs = pairs.filter((pair, index) =>
  pairs.findIndex((other) => other.chat === pair.chat && other.work === pair.work) === index
);
const segments = [];
for (const pair of uniquePairs) {{
  const branchUnder = (leaf, ancestor) => {{
    let current = leaf;
    while (current && current.parentElement && current.parentElement !== ancestor) {{
      current = current.parentElement;
    }}
    return current && current.parentElement === ancestor ? current : null;
  }};
  const chatBranch = branchUnder(pair.chat, pair.ancestor);
  const workBranch = branchUnder(pair.work, pair.ancestor);
  if (chatBranch && workBranch && chatBranch !== workBranch && visible(chatBranch)) {{
    segments.push(chatBranch);
  }}
}}
const uniqueSegments = segments.filter((el, index) => segments.indexOf(el) === index);

if (uniquePairs.length === 1 && uniqueSegments.length === 1) {{
  const pair = uniquePairs[0];
  const chatBranch = uniqueSegments[0];
  const distanceToLeaf = (ancestor, leaf) => {{
    let current = leaf;
    let distance = 0;
    while (current && current !== ancestor) {{
      current = current.parentElement;
      distance += 1;
    }}
    return current === ancestor ? distance : 999;
  }};
  const pairedInteractive = interactiveMatches
    .filter((el) => (el === chatBranch || chatBranch.contains(el)))
    .filter((el) => el === pair.chat || el.contains(pair.chat))
    .sort((a, b) => distanceToLeaf(a, pair.chat) - distanceToLeaf(b, pair.chat));
  const target = pairedInteractive[0] || pair.chat;
  return mark(target, {{
    strategy: 'paired_segment',
    interactive_matches: interactiveMatches.length,
    paired_matches: 1,
    segment_matches: 1,
  }});
}}

return {{
  marked: false,
  strategy: 'none',
  interactive_matches: interactiveMatches.length,
  paired_matches: uniquePairs.length,
  segment_matches: uniqueSegments.length,
}};
"""

_CLEAN_SWITCH_MARKER_JS = rf"""
document.querySelectorAll('[{_SWITCH_MARKER_ATTR}]').forEach(
  (el) => el.removeAttribute('{_SWITCH_MARKER_ATTR}')
);
return true;
"""

_RATE_LIMIT_ACK_JS = rf"""
const marker = '{_RATE_LIMIT_ACK_MARKER_ATTR}';
document.querySelectorAll(`[${{marker}}]`).forEach(
  (el) => el.removeAttribute(marker)
);
const visible = (el) => {{
  if (!el) return false;
  const style = window.getComputedStyle ? window.getComputedStyle(el) : null;
  const rect = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
  return (!style || (style.display !== 'none' && style.visibility !== 'hidden')) &&
    (!rect || (rect.width > 0 && rect.height > 0));
}};
const norm = (value) => String(value || '')
  .replace(/[\s\u200b-\u200d\ufeff]+/g, ' ')
  .trim()
  .toLowerCase();
const rateLike = (value) => {{
  const text = norm(value);
  return text.includes('too many requests') ||
    text.includes('making requests too quickly') ||
    text.includes('temporarily limited access to your conversations') ||
    text.includes('请求过于频繁') ||
    text.includes('暂时限制你访问对话记录');
}};
const dialogs = Array.from(document.querySelectorAll(
  '[role="dialog"],[aria-modal="true"]'
)).filter(visible).filter((el) => rateLike(el.innerText || el.textContent));

if (dialogs.length !== 1) {{
  return {{marked:false, dialogs:dialogs.length, ack_matches:0}};
}}

const ackValues = new Set([
  'got it',
  'ok',
  'okay',
  '明白了',
  '知道了',
]);
const buttons = Array.from(dialogs[0].querySelectorAll(
  'button,[role="button"]'
)).filter(visible);
const matches = buttons.filter((el) => {{
  const text = norm(el.innerText || el.textContent);
  const aria = norm(el.getAttribute && el.getAttribute('aria-label'));
  return ackValues.has(text) || ackValues.has(aria);
}});

if (matches.length !== 1) {{
  return {{marked:false, dialogs:1, ack_matches:matches.length}};
}}

matches[0].setAttribute(marker, '1');
return {{marked:true, dialogs:1, ack_matches:1}};
"""

_CLEAN_RATE_LIMIT_ACK_MARKER_JS = rf"""
document.querySelectorAll('[{_RATE_LIMIT_ACK_MARKER_ATTR}]').forEach(
  (el) => el.removeAttribute('{_RATE_LIMIT_ACK_MARKER_ATTR}')
);
return true;
"""

# ChatGPT can paint an apparently-ready Chat composer before account-level mode
# restoration finishes and flips the root page back to Work. Acceptance must
# observe a short consecutive ready window before it is allowed to send.
READY_STABLE_SAMPLES = 10
POLL_SECONDS = 0.15


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


def _switch_probe(result: Any) -> dict[str, Any]:
    """Return only sanitized selector metadata from the acceptance click probe."""
    if not isinstance(result, dict):
        return {
            "strategy": "invalid_result",
            "interactive_matches": 0,
            "paired_matches": 0,
            "segment_matches": 0,
        }

    def _count(name: str) -> int:
        try:
            return max(0, int(result.get(name, 0) or 0))
        except (TypeError, ValueError):
            return 0

    strategy = str(result.get("strategy") or "none")
    if strategy not in {"interactive", "paired_segment", "none"}:
        strategy = "unknown"
    return {
        "strategy": strategy,
        "interactive_matches": _count("interactive_matches"),
        "paired_matches": _count("paired_matches"),
        "segment_matches": _count("segment_matches"),
    }


def _physical_click_marked_chat(tab: Any, result: Any) -> bool:
    """Perform one real browser-level click on the unique marked Chat target."""
    if not isinstance(result, dict) or not result.get("marked"):
        return False
    try:
        element = tab.ele(f"css:{_SWITCH_MARKER_SELECTOR}", timeout=1.5)
        if not element:
            return False
        clicked = element.click(by_js=False, timeout=2.0, wait_stop=True)
        return clicked is not False
    except Exception:
        return False
    finally:
        try:
            tab.run_js(_CLEAN_SWITCH_MARKER_JS)
        except Exception:
            pass


def _physical_click_rate_limit_ack(tab: Any) -> bool:
    """Dismiss one acknowledgement-only rate-limit dialog, never Retry/quota controls."""

    try:
        result = tab.run_js(_RATE_LIMIT_ACK_JS)
    except Exception:
        return False

    if not isinstance(result, dict) or not result.get("marked"):
        return False

    try:
        element = tab.ele(
            f"css:{_RATE_LIMIT_ACK_MARKER_SELECTOR}",
            timeout=1.5,
        )
        if not element:
            return False
        clicked = element.click(
            by_js=False,
            timeout=2.0,
            wait_stop=True,
        )
        return clicked is not False
    except Exception:
        return False
    finally:
        try:
            tab.run_js(
                _CLEAN_RATE_LIMIT_ACK_MARKER_JS
            )
        except Exception:
            pass


def _wait_after_rate_limit_dismiss(
    tab: Any,
    timeout_seconds: float,
) -> Any:
    """Wait for a dismissed stale notice to disappear.

    If the account is genuinely still limited, the dialog/status will remain or
    reappear and the caller continues to fail closed as rate_limited.
    """

    deadline = time.monotonic() + max(
        1.0,
        float(timeout_seconds),
    )
    state = inspect_chatgpt_surface(
        tab,
        target_count=1,
    )
    ready_samples = 0

    while time.monotonic() < deadline:
        if (
            state.blocking_reason == "none"
            and state.surface_kind == "chat"
        ):
            ready_samples += 1
            if ready_samples >= max(
                1,
                int(READY_STABLE_SAMPLES),
            ):
                break
        else:
            ready_samples = 0
            if state.blocking_reason not in {
                "rate_limited",
                "unknown_surface",
                "prompt_missing",
                "send_missing",
            }:
                break

        time.sleep(POLL_SECONDS)
        state = inspect_chatgpt_surface(
            tab,
            target_count=1,
        )

    return state


def _wait_initial_surface(tab: Any, timeout_seconds: float) -> Any:
    """Wait until the fresh target has reached a stable, classifiable surface.

    A newly-created root can transiently expose a Chat composer before the mode
    chrome restores Work. A ready Chat state therefore has to remain unchanged
    for a bounded consecutive sample window. Definitive blockers such as Work
    still return immediately so acceptance can normalize them safely.
    """
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    state = inspect_chatgpt_surface(tab, target_count=1)
    transient = {"unknown_surface", "prompt_missing", "send_missing"}
    dirty_settle_samples = 0
    max_dirty_settle_samples = 12
    ready_samples = 0

    while time.monotonic() < deadline:
        if state.blocking_reason == "none" and state.surface_kind == "chat":
            ready_samples += 1
            if ready_samples >= max(1, int(READY_STABLE_SAMPLES)):
                break
            time.sleep(POLL_SECONDS)
            state = inspect_chatgpt_surface(tab, target_count=1)
            continue

        ready_samples = 0

        if state.blocking_reason == "composer_not_empty":
            dirty_settle_samples += 1
            if dirty_settle_samples >= max_dirty_settle_samples:
                break
            time.sleep(POLL_SECONDS)
            state = inspect_chatgpt_surface(tab, target_count=1)
            continue

        if state.blocking_reason not in transient:
            break

        # A fresh ChatGPT root may expose the composer before the account-level
        # Chat/Work mode chrome has finished restoring. Keep polling transient
        # states even when the prompt is already visible and empty. If the
        # surface remains genuinely ambiguous for the whole bounded wait, run()
        # may still use the exact safe Chat normalization path afterward.
        time.sleep(POLL_SECONDS)
        state = inspect_chatgpt_surface(tab, target_count=1)
    return state


def _wait_after_chat_switch(tab: Any, timeout_seconds: float) -> Any:
    """Wait for a physical Work-to-Chat click to settle into stable Chat.

    Immediately after the browser-level click, React may still expose the old
    Work-selected DOM for one or more frames. Unlike the initial probe, Work is
    therefore transient inside this bounded post-click window. Safety blockers
    unrelated to mode settling remain fail-closed.
    """
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    state = inspect_chatgpt_surface(tab, target_count=1)
    transient = {"work_surface", "unknown_surface", "prompt_missing", "send_missing"}
    ready_samples = 0

    while time.monotonic() < deadline:
        if state.blocking_reason == "none" and state.surface_kind == "chat":
            ready_samples += 1
            if ready_samples >= max(1, int(READY_STABLE_SAMPLES)):
                break
        else:
            ready_samples = 0
            if state.blocking_reason not in transient:
                break
            if not state.composer_empty:
                break

        time.sleep(POLL_SECONDS)
        state = inspect_chatgpt_surface(tab, target_count=1)

    return state


def run(*, timeout_seconds: float = 8.0) -> int:
    actions: list[str] = []
    switch_probe: dict[str, Any] | None = None
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

    # ChatGPT can leave an acknowledgement-only "requests too frequent" dialog
    # visible after the cooldown has already ended. Dismiss that stale notice
    # once and re-probe. This does not bypass an active limit: if the blocker
    # remains or reappears, preflight still fails closed as rate_limited.
    if state.blocking_reason == "rate_limited":
        if _physical_click_rate_limit_ack(tab):
            actions.append("dismiss_rate_limit_notice")
            state = _wait_after_rate_limit_dismiss(
                tab,
                timeout_seconds,
            )

    if _can_safely_select_chat(state):
        original_reason = state.blocking_reason
        result = tab.run_js(_SWITCH_CHAT_JS)
        switch_probe = _switch_probe(result)
        if not _physical_click_marked_chat(tab, result):
            _emit(
                {
                    "ok": False,
                    "failure_class": _failure_class(original_reason),
                    "target_count": 1,
                    "surface_kind": state.surface_kind,
                    "blocking_reason": original_reason,
                    "actions": actions,
                    "switch_probe": switch_probe,
                }
            )
            return 1
        actions.append("switch_to_chat")
        state = _wait_after_chat_switch(tab, timeout_seconds)

    if state.blocking_reason not in {"none", "composer_not_empty"}:
        payload = {
            "ok": False,
            "failure_class": _failure_class(state.blocking_reason),
            "target_count": 1,
            "surface_kind": state.surface_kind,
            "blocking_reason": state.blocking_reason,
            "actions": actions,
        }
        if switch_probe is not None:
            payload["switch_probe"] = switch_probe
        _emit(payload)
        return 1

    if not state.composer_empty:
        payload = {
            "ok": False,
            "failure_class": "chatgpt_composer_not_empty",
            "target_count": 1,
            "surface_kind": state.surface_kind,
            "blocking_reason": "composer_not_empty",
            "actions": actions,
        }
        if switch_probe is not None:
            payload["switch_probe"] = switch_probe
        _emit(payload)
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
        state = _wait_initial_surface(tab, timeout_seconds)

    if not state.surface_ready:
        payload = {
            "ok": False,
            "failure_class": _failure_class(state.blocking_reason),
            "target_count": 1,
            "surface_kind": state.surface_kind,
            "pathname_class": state.pathname_class,
            "composer_empty": state.composer_empty,
            "blocking_reason": state.blocking_reason,
            "actions": actions,
        }
        if switch_probe is not None:
            payload["switch_probe"] = switch_probe
        _emit(payload)
        return 1

    payload = {
        "ok": True,
        "failure_class": "none",
        "target_count": 1,
        "surface_kind": state.surface_kind,
        "pathname_class": state.pathname_class,
        "composer_empty": state.composer_empty,
        "blocking_reason": state.blocking_reason,
        "actions": actions,
    }
    if switch_probe is not None:
        payload["switch_probe"] = switch_probe
    _emit(payload)
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
