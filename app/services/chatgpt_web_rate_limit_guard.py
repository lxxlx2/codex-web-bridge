"""Fail-closed ChatGPT Web rate-limit and ambiguous-submit guard.

The ChatGPT web surface can temporarily throttle conversation access while the
browser still exposes an enabled composer/send button. Treat that UI state as a
first-class transport condition so the send-confirmation fallback does not
hammer the same prompt repeatedly.

Design goals:
- detect the known ChatGPT rate-limit modal without reading conversation text;
- dismiss only the modal acknowledgement control when present;
- persist a small account/channel cooldown under ``~/.uwa`` so listener restarts
  do not immediately resume sending;
- wait out a throttle discovered before the initial submit, because no message
  has been dispatched yet;
- never auto-resend a ChatGPT prompt after an already-dispatched send becomes
  ambiguous. An ambiguous submit must fail closed instead of risking a duplicate
  message;
- emit standard HTTP-like terminal errors so the existing workflow/error stack
  unwinds immediately instead of leaving the browser session busy until the
  generic stuck watchdog fires.

The implementation is intentionally a narrow runtime compatibility patch over
``WorkflowExecutorSendMixin``. Other sites keep their existing retry behavior.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.config import WorkflowError, logger


_BACKOFF_SECONDS = (20.0, 45.0, 90.0)
_STATE_LOCK = threading.RLock()
_INSTALLED = False

_RATE_LIMIT_JS = r"""
return (function() {
    const visible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle ? window.getComputedStyle(el) : null;
        const rect = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
        return (!style || (style.display !== 'none' && style.visibility !== 'hidden'))
            && (!rect || (rect.width > 0 && rect.height > 0));
    };
    const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim();
    const low = (value) => norm(value).toLowerCase();
    const english = [
        'making requests too quickly',
        'temporarily limited access to your conversations',
        'please wait a few minutes before trying again'
    ];
    const chinese = [
        '请求过于频繁',
        '暂时限制你访问对话记录',
        '请稍等几分钟后再重试'
    ];
    const matches = (text) => {
        const value = low(text);
        const enHits = english.filter((item) => value.includes(item)).length;
        const zhHits = chinese.filter((item) => value.includes(item)).length;
        return value.includes('too many requests') || enHits >= 2 || zhHits >= 2;
    };

    const candidates = Array.from(document.querySelectorAll(
        '[role="dialog"], [aria-modal="true"], [data-radix-portal]'
    )).filter(visible);
    const target = candidates.find((el) => matches(el.innerText || el.textContent));
    if (!target) {
        return {detected: false, dismissed: false};
    }

    const ackPatterns = ['got it', 'ok', 'okay', '明白了', '知道了', '确定'];
    const buttons = Array.from(target.querySelectorAll('button,[role="button"]')).filter(visible);
    const ack = buttons.find((button) => {
        const text = low(button.innerText || button.textContent || button.getAttribute('aria-label'));
        return ackPatterns.some((item) => text === item || text.includes(item));
    });

    let dismissed = false;
    if (ack) {
        try {
            ack.click();
            dismissed = true;
        } catch (_) {}
    }
    return {detected: true, dismissed};
})();
"""


def _state_path() -> Path:
    raw = str(os.getenv("UWA_CHATGPT_RATE_LIMIT_STATE") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".uwa" / "chatgpt-rate-limit.json"


def _load_state() -> Dict[str, Any]:
    path = _state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return dict(data) if isinstance(data, dict) else {}


def _save_state(state: Dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _record_rate_limit(now: float | None = None) -> Dict[str, Any]:
    current = time.time() if now is None else float(now)
    with _STATE_LOCK:
        state = _load_state()
        try:
            last_seen = float(state.get("last_seen_epoch", 0.0) or 0.0)
        except (TypeError, ValueError):
            last_seen = 0.0
        try:
            previous_hits = int(state.get("hits", 0) or 0)
        except (TypeError, ValueError):
            previous_hits = 0

        if last_seen <= 0 or current - last_seen > 600.0:
            previous_hits = 0
        hits = max(1, previous_hits + 1)
        delay = _BACKOFF_SECONDS[min(hits - 1, len(_BACKOFF_SECONDS) - 1)]
        try:
            existing_until = float(state.get("blocked_until_epoch", 0.0) or 0.0)
        except (TypeError, ValueError):
            existing_until = 0.0
        blocked_until = max(existing_until, current + delay)
        updated = {
            "version": 1,
            "hits": hits,
            "last_seen_epoch": current,
            "blocked_until_epoch": blocked_until,
            "backoff_seconds": delay,
        }
        _save_state(updated)
        return updated


def rate_limit_status(now: float | None = None) -> Dict[str, Any]:
    current = time.time() if now is None else float(now)
    with _STATE_LOCK:
        state = _load_state()
    try:
        blocked_until = float(state.get("blocked_until_epoch", 0.0) or 0.0)
    except (TypeError, ValueError):
        blocked_until = 0.0
    remaining = max(0.0, blocked_until - current)
    return {
        "cooldown_active": remaining > 0.0,
        "cooldown_remaining_seconds": round(remaining, 3),
        "hits": int(state.get("hits", 0) or 0),
    }


def _tab_url(executor: Any) -> str:
    tab = getattr(executor, "tab", None)
    try:
        return str(getattr(tab, "url", "") or "")
    except Exception:
        return ""


def _is_chatgpt_executor(executor: Any) -> bool:
    return "chatgpt.com" in _tab_url(executor).lower()


def _probe_rate_limit(executor: Any) -> Dict[str, Any]:
    tab = getattr(executor, "tab", None)
    if tab is None or not hasattr(tab, "run_js"):
        return {"detected": False, "dismissed": False}
    try:
        result = tab.run_js(_RATE_LIMIT_JS) or {}
    except Exception as exc:
        logger.debug(f"[CHATGPT_WEB_GUARD] rate-limit probe failed: {exc}")
        return {"detected": False, "dismissed": False}
    return dict(result) if isinstance(result, dict) else {"detected": False, "dismissed": False}


def _cancelled(executor: Any) -> bool:
    checker = getattr(executor, "_check_cancelled", None)
    return bool(callable(checker) and checker())


def _raise_rate_limited(*, state: Optional[Dict[str, Any]] = None) -> None:
    current = dict(state or _record_rate_limit())
    logger.warning(
        "[CHATGPT_WEB_GUARD] ChatGPT Web rate-limit remains active; "
        "automatic resend disabled and terminal 429 propagated "
        f"(backoff={float(current.get('backoff_seconds', 0.0) or 0.0):.0f}s, "
        f"hits={int(current.get('hits', 0) or 0)})"
    )
    raise WorkflowError("429 Too Many Requests: chatgpt_web_rate_limited")


def _wait_existing_cooldown(executor: Any) -> bool:
    status = rate_limit_status()
    remaining = float(status.get("cooldown_remaining_seconds", 0.0) or 0.0)
    if remaining <= 0:
        return not _cancelled(executor)

    logger.warning(
        "[CHATGPT_WEB_GUARD] ChatGPT Web channel is cooling down; "
        f"waiting {remaining:.1f}s before the next submit"
    )
    deadline = time.time() + remaining
    while time.time() < deadline:
        if _cancelled(executor):
            return False
        time.sleep(min(0.25, max(0.0, deadline - time.time())))
    return not _cancelled(executor)


def guard_before_initial_send(executor: Any) -> None:
    if not _is_chatgpt_executor(executor):
        return
    if not _wait_existing_cooldown(executor):
        raise WorkflowError("request_cancelled")

    state = _probe_rate_limit(executor)
    if not state.get("detected"):
        return

    cooldown = _record_rate_limit()
    logger.warning(
        "[CHATGPT_WEB_GUARD] ChatGPT Web rate-limit modal detected before submit; "
        "no message has been dispatched, so the initial send will wait for the "
        "channel cooldown instead of failing immediately "
        f"(backoff={cooldown['backoff_seconds']:.0f}s, hits={cooldown['hits']}, "
        f"dismissed={bool(state.get('dismissed'))})"
    )

    if not _wait_existing_cooldown(executor):
        raise WorkflowError("request_cancelled")

    after_cooldown = _probe_rate_limit(executor)
    if after_cooldown.get("detected"):
        _raise_rate_limited(state=cooldown)

    logger.info(
        "[CHATGPT_WEB_GUARD] pre-submit cooldown completed and the visible "
        "rate-limit modal is clear; allowing one initial send"
    )


def guard_before_retry(executor: Any) -> None:
    if not _is_chatgpt_executor(executor):
        return

    state = _probe_rate_limit(executor)
    if state.get("detected"):
        cooldown = _record_rate_limit()
        _raise_rate_limited(state=cooldown)

    logger.warning(
        "[CHATGPT_WEB_GUARD] prior ChatGPT send was dispatched but submission is ambiguous; "
        "suppressing automatic resend to avoid duplicate messages"
    )
    raise WorkflowError("422 Unprocessable Entity: chatgpt_send_submission_unknown")


def install_chatgpt_web_rate_limit_guard() -> None:
    """Install the narrow ChatGPT-only send guards once per process."""
    global _INSTALLED
    if _INSTALLED:
        return

    from app.core.workflow.executor_send import WorkflowExecutorSendMixin

    wait_name = "_wait_for_send_idle_before_action"
    retry_name = "_execute_send_retry_action"
    wait_marker = "_uwa_chatgpt_rate_limit_guarded"
    retry_marker = "_uwa_chatgpt_ambiguous_retry_guarded"

    current_wait = getattr(WorkflowExecutorSendMixin, wait_name)
    current_retry = getattr(WorkflowExecutorSendMixin, retry_name)

    if not getattr(current_wait, wait_marker, False):
        def guarded_wait(self: Any, send_selector: str):
            guard_before_initial_send(self)
            return current_wait(self, send_selector)

        setattr(guarded_wait, wait_marker, True)
        setattr(WorkflowExecutorSendMixin, wait_name, guarded_wait)

    if not getattr(current_retry, retry_marker, False):
        def guarded_retry(self: Any, *args: Any, **kwargs: Any):
            guard_before_retry(self)
            return current_retry(self, *args, **kwargs)

        setattr(guarded_retry, retry_marker, True)
        setattr(WorkflowExecutorSendMixin, retry_name, guarded_retry)

    _INSTALLED = True
    logger.info(
        "[CHATGPT_WEB_GUARD] rate-limit circuit breaker and ambiguous-submit guard installed"
    )


__all__ = [
    "guard_before_initial_send",
    "guard_before_retry",
    "install_chatgpt_web_rate_limit_guard",
    "rate_limit_status",
]
