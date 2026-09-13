"""Fail-closed ChatGPT Web transport guard.

The browser can expose an enabled composer while the ChatGPT surface is in Work
mode, quota exhausted, rate limited, authentication/challenge blocked, or after
an already-dispatched send whose submission state is ambiguous. Treat those
states as first-class transport conditions and never blindly resend.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.config import WorkflowError, logger
from app.services.chatgpt_web_surface import inspect_chatgpt_surface


_BACKOFF_SECONDS = (20.0, 45.0, 90.0)
_STATE_LOCK = threading.RLock()
_INSTALLED = False

_RATE_LIMIT_ACK_JS = r"""
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
    const matches = (text) => {
        const value = low(text);
        return value.includes('too many requests') ||
            value.includes('making requests too quickly') ||
            value.includes('temporarily limited access to your conversations') ||
            value.includes('请求过于频繁') ||
            value.includes('暂时限制你访问对话记录');
    };
    const candidates = Array.from(document.querySelectorAll(
        '[role="dialog"],[aria-modal="true"],[data-radix-portal]'
    )).filter(visible);
    const target = candidates.find((el) => matches(el.innerText || el.textContent));
    if (!target) return {detected: false, dismissed: false};

    const ackPatterns = ['got it', 'ok', 'okay', '明白了', '知道了', '确定'];
    const buttons = Array.from(target.querySelectorAll('button,[role="button"]')).filter(visible);
    const ack = buttons.find((button) => {
        const text = low(
            button.innerText || button.textContent || button.getAttribute('aria-label')
        );
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
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
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


def _surface_reason(executor: Any) -> str:
    tab = getattr(executor, "tab", None)
    if tab is None or not hasattr(tab, "run_js"):
        return "unknown_surface"
    try:
        return inspect_chatgpt_surface(tab, target_count=1).blocking_reason
    except Exception as exc:
        logger.debug(f"[CHATGPT_WEB_GUARD] surface probe failed: {exc}")
        return "surface_probe_failed"


def _ack_rate_limit(executor: Any) -> Dict[str, Any]:
    tab = getattr(executor, "tab", None)
    if tab is None or not hasattr(tab, "run_js"):
        return {"detected": False, "dismissed": False}
    try:
        result = tab.run_js(_RATE_LIMIT_ACK_JS) or {}
    except Exception as exc:
        logger.debug(f"[CHATGPT_WEB_GUARD] rate-limit acknowledgement probe failed: {exc}")
        return {"detected": False, "dismissed": False}
    return dict(result) if isinstance(result, dict) else {
        "detected": False,
        "dismissed": False,
    }


def _cancelled(executor: Any) -> bool:
    checker = getattr(executor, "_check_cancelled", None)
    return bool(callable(checker) and checker())


def _terminal(status: int, label: str, code: str) -> None:
    raise WorkflowError(f"stream_terminal_error:{status} {label}: {code}")


def _raise_surface_blocker(reason: str) -> None:
    if reason == "work_surface":
        _terminal(409, "Conflict", "chatgpt_web_work_surface")
    if reason == "work_quota_exhausted":
        _terminal(429, "Too Many Requests", "chatgpt_web_work_quota_exhausted")
    if reason == "usage_exhausted":
        _terminal(429, "Too Many Requests", "chatgpt_web_usage_exhausted")
    if reason == "auth_required":
        _terminal(503, "Service Unavailable", "chatgpt_web_auth_required")
    if reason == "challenge":
        _terminal(503, "Service Unavailable", "chatgpt_web_challenge")
    if reason in {"unknown_surface", "surface_probe_failed"}:
        _terminal(503, "Service Unavailable", "chatgpt_web_surface_unknown")


def _raise_rate_limited(*, state: Optional[Dict[str, Any]] = None) -> None:
    current = dict(state or _record_rate_limit())
    logger.warning(
        "[CHATGPT_WEB_GUARD] ChatGPT Web rate-limit remains active; "
        "automatic resend disabled and terminal 429 propagated "
        f"(backoff={float(current.get('backoff_seconds', 0.0) or 0.0):.0f}s, "
        f"hits={int(current.get('hits', 0) or 0)})"
    )
    _terminal(429, "Too Many Requests", "chatgpt_web_rate_limited")


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

    reason = _surface_reason(executor)
    if reason == "rate_limited":
        ack = _ack_rate_limit(executor)
        cooldown = _record_rate_limit()
        logger.warning(
            "[CHATGPT_WEB_GUARD] ChatGPT Web rate-limit detected before submit; "
            "no message has been dispatched, so one bounded cooldown is allowed "
            f"(backoff={cooldown['backoff_seconds']:.0f}s, "
            f"hits={cooldown['hits']}, dismissed={bool(ack.get('dismissed'))})"
        )
        if not _wait_existing_cooldown(executor):
            raise WorkflowError("request_cancelled")
        if _surface_reason(executor) == "rate_limited":
            _raise_rate_limited(state=cooldown)
        logger.info(
            "[CHATGPT_WEB_GUARD] pre-submit cooldown completed and rate-limit "
            "blocker is clear; allowing one initial send"
        )
        return

    # composer_not_empty is expected here because the workflow has already
    # filled the prompt. send_missing can be transient while the UI settles.
    if reason not in {"none", "composer_not_empty", "send_missing"}:
        _raise_surface_blocker(reason)


def guard_before_retry(executor: Any) -> None:
    if not _is_chatgpt_executor(executor):
        return

    reason = _surface_reason(executor)
    if reason == "rate_limited":
        _ack_rate_limit(executor)
        cooldown = _record_rate_limit()
        _raise_rate_limited(state=cooldown)
    if reason not in {"none", "composer_not_empty", "send_missing"}:
        _raise_surface_blocker(reason)

    logger.warning(
        "[CHATGPT_WEB_GUARD] prior ChatGPT send was dispatched but submission "
        "is ambiguous; suppressing automatic resend to avoid duplicate messages"
    )
    _terminal(422, "Unprocessable Entity", "chatgpt_send_submission_unknown")


def install_chatgpt_web_rate_limit_guard() -> None:
    """Install ChatGPT-only send guards once per process."""
    global _INSTALLED
    if _INSTALLED:
        return

    from app.core.workflow.executor_send import WorkflowExecutorSendMixin

    wait_name = "_wait_for_send_idle_before_action"
    retry_name = "_execute_send_retry_action"
    wait_marker = "_uwa_chatgpt_surface_guarded"
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
        "[CHATGPT_WEB_GUARD] surface blocker, rate-limit circuit breaker and "
        "ambiguous-submit guard installed"
    )


__all__ = [
    "guard_before_initial_send",
    "guard_before_retry",
    "install_chatgpt_web_rate_limit_guard",
    "rate_limit_status",
]
