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
const norm = (value) => String(value || '').replace(/[\s\u200b-\u200d\ufeff]+/g, ' ').trim().toLowerCase();
const exactChat = new Set(['chat', '聊天']);
const exactWork = new Set(['work', '工作']);
const exactValue = (el, values) => {
  if (!el) return false;
  const text = norm(el.innerText || el.textContent);
  const aria = norm(el.getAttribute && el.getAttribute('aria-label'));
  return values.has(text) || values.has(aria);
};

const interactiveSelector = [
  'button', 'a', '[role="tab"]', '[role="button"]',
  '[aria-selected]', '[aria-pressed]', '[data-state]', '[data-selected]',
  '[tabindex]'
].join(',');
const interactive = Array.from(document.querySelectorAll(interactiveSelector))
  .filter(visible);
const interactiveMatches = interactive.filter((el) => exactValue(el, exactChat));

// Historical/semantic path: one unambiguous interactive Chat control.
if (interactiveMatches.length === 1) {
  interactiveMatches[0].click();
  return {
    clicked: true,
    strategy: 'interactive',
    interactive_matches: 1,
    paired_matches: 0,
    segment_matches: 0,
  };
}

// Current ChatGPT can render the Chat/Work selector as nested div/span labels.
// Clicking the leaf label is insufficient in this UI: the actual event handler
// lives on the Chat segment branch. Resolve a unique Chat/Work pair inside the
// smallest shared ancestor, then click only the direct Chat-side branch. This
// stays fail-closed when the pair or branch is ambiguous.
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
for (const chat of chatLabels) {
  let ancestor = chat.parentElement;
  for (let depth = 0; ancestor && ancestor !== document.body && depth < 5; depth += 1) {
    const chatsHere = chatLabels.filter((el) => ancestor.contains(el));
    const worksHere = workLabels.filter((el) => ancestor.contains(el));
    if (chatsHere.length === 1 && worksHere.length === 1) {
      pairs.push({chat, work: worksHere[0], root: ancestor});
      break;
    }
    ancestor = ancestor.parentElement;
  }
}

const pairedMatches = pairs.map((pair) => pair.chat);
const branchUnder = (root, leaf) => {
  let node = leaf;
  while (node && node.parentElement && node.parentElement !== root) {
    node = node.parentElement;
  }
  return node && node.parentElement === root ? node : null;
};

const segmentCandidates = pairs.map((pair) => {
  const chatBranch = branchUnder(pair.root, pair.chat);
  const workBranch = branchUnder(pair.root, pair.work);
  if (!chatBranch || !workBranch || chatBranch === workBranch) return null;
  if (!visible(chatBranch) || !visible(workBranch)) return null;
  if (!chatBranch.contains(pair.chat) || !workBranch.contains(pair.work)) return null;
  // The Chat branch must not contain the Work label and vice versa.
  if (chatBranch.contains(pair.work) || workBranch.contains(pair.chat)) return null;
  return chatBranch;
}).filter(Boolean);

const uniqueSegments = segmentCandidates.filter(
  (candidate, index, all) => all.indexOf(candidate) === index
);

if (uniqueSegments.length === 1) {
  uniqueSegments[0].click();
  return {
    clicked: true,
    strategy: 'paired_segment',
    interactive_matches: interactiveMatches.length,
    paired_matches: pairedMatches.length,
    segment_matches: 1,
  };
}

return {
  clicked: false,
  strategy: 'none',
  interactive_matches: interactiveMatches.length,
  paired_matches: pairedMatches.length,
  segment_matches: uniqueSegments.length,
};
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
        if state.prompt_present and state.composer_empty:
            # An ambiguous rendered surface may already be safe to normalize
            # through the exact Chat control; do not wait the whole timeout.
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

    # Acceptance owns this disposable target. If Chat/Work controls are visible
    # but selection semantics are absent, selecting one exact Chat control is a
    # safe normalization action only while the composer is empty. Normal runtime
    # remains fail-closed and never performs this switch automatically.
    if _can_safely_select_chat(state):
        original_reason = state.blocking_reason
        result = tab.run_js(_SWITCH_CHAT_JS)
        switch_probe = _switch_probe(result)
        if not isinstance(result, dict) or not result.get("clicked"):
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
        state = _wait_initial_surface(tab, timeout_seconds)

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
