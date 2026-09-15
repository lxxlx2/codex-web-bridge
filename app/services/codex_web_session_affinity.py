"""In-process ChatGPT Web conversation affinity for Codex tool loops.

Codex Responses uses ``previous_response_id`` to continue an agent turn.  The
browser side should mirror that continuity: one Codex tool loop stays on one
ChatGPT conversation and sends only the new delta.  If the mapping is missing
(for example after a UWA restart), callers fall back to a fresh ChatGPT chat plus
reconstructed Responses history.

Only a validated ChatGPT pathname is kept in memory.  Conversation content,
cookies, local storage, prompts and tool output are never stored here.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.core import get_browser
from app.core.config import get_logger
from app.core.tab_pool import TabSession
from app.services.chatgpt_web_mode import ChatGPTWebModeError, _find_chatgpt_tab


logger = get_logger("CODEX_WEB_AFFINITY")
_CHAT_PATH_RE = re.compile(r"^/c/[A-Za-z0-9:_-]{8,192}$")
_BINDINGS: "OrderedDict[str, WebConversationBinding]" = OrderedDict()
_BINDINGS_LOCK = threading.RLock()
_PATCH_LOCK = threading.Lock()
_PATCH_INSTALLED = False
_ORIGINAL_SHOULD_START_NEW = None
_REUSE_TAB_IDS: set[str] = set()
_REUSE_TAB_IDS_LOCK = threading.RLock()


@dataclass(frozen=True)
class WebConversationBinding:
    response_id: str
    pathname: str
    model: str
    reasoning: str
    bound_at: float


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = str(os.getenv(name, str(default)) or str(default)).strip()
    try:
        value = int(raw)
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def affinity_enabled() -> bool:
    raw = str(os.getenv("UWA_CODEX_WEB_SESSION_AFFINITY", "true") or "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def affinity_ttl_sec() -> int:
    return _env_int("UWA_CODEX_WEB_SESSION_TTL_SEC", 7200, 60, 86400)


def affinity_max_entries() -> int:
    return _env_int("UWA_CODEX_WEB_SESSION_MAX_ENTRIES", 512, 16, 4096)


def _normalize_model(value: Any) -> str:
    return str(value or "").strip().casefold()


def _normalize_reasoning(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("effort")
    return str(value or "").strip().lower()


def _valid_pathname(value: Any) -> str:
    pathname = str(value or "").strip()
    return pathname if _CHAT_PATH_RE.fullmatch(pathname) else ""


def _prune_locked(now: Optional[float] = None) -> None:
    current = float(now if now is not None else time.time())
    cutoff = current - affinity_ttl_sec()
    expired = [key for key, item in _BINDINGS.items() if item.bound_at < cutoff]
    for key in expired:
        _BINDINGS.pop(key, None)
    while len(_BINDINGS) > affinity_max_entries():
        _BINDINGS.popitem(last=False)


def bind_response_to_conversation(
    response_id: str,
    pathname: str,
    *,
    model: Any,
    reasoning: Any,
) -> bool:
    if not affinity_enabled():
        return False
    key = str(response_id or "").strip()
    safe_path = _valid_pathname(pathname)
    if not key or not safe_path:
        return False

    normalized_model = _normalize_model(model)
    normalized_reasoning = _normalize_reasoning(reasoning)
    now = time.time()
    binding = WebConversationBinding(
        response_id=key,
        pathname=safe_path,
        model=normalized_model,
        reasoning=normalized_reasoning,
        bound_at=now,
    )
    with _BINDINGS_LOCK:
        _prune_locked(now)
        existing = _BINDINGS.get(key)
        if existing is not None:
            identical = (
                existing.pathname == safe_path
                and existing.model == normalized_model
                and existing.reasoning == normalized_reasoning
            )
            if not identical:
                logger.warning(
                    "[CODEX_WEB_AFFINITY] rejected response identity rebind to a different "
                    "ChatGPT conversation/model/reasoning (path redacted)"
                )
                return False
        _BINDINGS[key] = binding
        _BINDINGS.move_to_end(key)
        _prune_locked(now)
    logger.info("[CODEX_WEB_AFFINITY] bound response to ChatGPT conversation (path redacted)")
    return True


def resolve_conversation_binding(
    previous_response_id: Any,
    *,
    model: Any,
    reasoning: Any,
) -> Optional[WebConversationBinding]:
    if not affinity_enabled():
        return None
    key = str(previous_response_id or "").strip()
    if not key:
        return None
    with _BINDINGS_LOCK:
        _prune_locked()
        binding = _BINDINGS.get(key)
        if binding is None:
            return None
        if binding.model != _normalize_model(model):
            return None
        requested_reasoning = _normalize_reasoning(reasoning)
        if requested_reasoning and binding.reasoning and binding.reasoning != requested_reasoning:
            return None
        _BINDINGS.move_to_end(key)
        return binding


def affinity_status() -> Dict[str, Any]:
    with _BINDINGS_LOCK:
        _prune_locked()
        count = len(_BINDINGS)
    with _REUSE_TAB_IDS_LOCK:
        active_reuse_tabs = len(_REUSE_TAB_IDS)
    return {
        "enabled": affinity_enabled(),
        "binding_count": count,
        "active_reuse_tabs": active_reuse_tabs,
        "ttl_sec": affinity_ttl_sec(),
        "max_entries": affinity_max_entries(),
        "persistent": False,
        "fallback": "fresh_chat_plus_reconstructed_history",
    }


def _probe_current_tab(tab: Any) -> Dict[str, Any]:
    result = tab.run_js(
        "return {pathname:String(location.pathname||''),"
        "prompt:!!document.querySelector('#prompt-textarea')||"
        "!!document.querySelector('[contenteditable=\"true\"][role=\"textbox\"]')};"
    )
    return result if isinstance(result, dict) else {}


def current_chatgpt_conversation_path() -> str:
    try:
        state = _probe_current_tab(_find_chatgpt_tab())
    except Exception:
        return ""
    if not bool(state.get("prompt")):
        return ""
    return _valid_pathname(state.get("pathname"))


def ensure_chatgpt_conversation(pathname: str, *, timeout_sec: float = 8.0) -> bool:
    safe_path = _valid_pathname(pathname)
    if not safe_path:
        return False
    try:
        tab = _find_chatgpt_tab()
        state = _probe_current_tab(tab)
        if _valid_pathname(state.get("pathname")) == safe_path and bool(state.get("prompt")):
            return True
        tab.get(f"https://chatgpt.com{safe_path}")
        deadline = time.monotonic() + max(1.0, float(timeout_sec))
        while time.monotonic() < deadline:
            time.sleep(0.12)
            state = _probe_current_tab(tab)
            if _valid_pathname(state.get("pathname")) == safe_path and bool(state.get("prompt")):
                return True
    except Exception as exc:
        logger.warning(f"[CODEX_WEB_AFFINITY] conversation restore failed: {type(exc).__name__}")
    return False


def _tab_id(value: Any) -> str:
    return str(getattr(value, "tab_id", "") or "").strip()


def _tab_id_has_reuse_hint(tab_id: str) -> bool:
    key = str(tab_id or "").strip()
    if not key:
        return False
    with _REUSE_TAB_IDS_LOCK:
        return key in _REUSE_TAB_IDS


def install_codex_workflow_reuse_policy() -> None:
    """Teach the generic workflow to honor a request-scoped Codex reuse hint.

    The generic UWA workflow normally starts a new conversation when its global
    reuse threshold is disabled. Codex owns conversation creation explicitly,
    so a Codex browser round marks the selected ChatGPT raw tab id as reusable.
    The raw-id set also works when DrissionPage returns another wrapper object for
    the same underlying tab. Other sites and ordinary UWA requests retain the
    original policy.
    """

    global _PATCH_INSTALLED, _ORIGINAL_SHOULD_START_NEW
    if _PATCH_INSTALLED:
        return
    with _PATCH_LOCK:
        if _PATCH_INSTALLED:
            return
        original = TabSession.should_start_new_conversation

        def _codex_aware_should_start(self: TabSession, *args: Any, **kwargs: Any) -> bool:
            session_tab = getattr(self, "tab", None)
            if (
                bool(getattr(self, "_codex_web_affinity_reuse", False))
                or bool(getattr(session_tab, "_uwa_codex_reuse_conversation", False))
                or _tab_id_has_reuse_hint(_tab_id(session_tab))
            ):
                return False
            return bool(original(self, *args, **kwargs))

        _ORIGINAL_SHOULD_START_NEW = original
        TabSession.should_start_new_conversation = _codex_aware_should_start
        _PATCH_INSTALLED = True


def _matching_tab_sessions(tab: Any):
    try:
        browser = get_browser()
        pool = getattr(browser, "tab_pool", None)
        sessions = getattr(pool, "_tabs", {}) if pool is not None else {}
        wanted_id = _tab_id(tab)
        for session in list(sessions.values()) if isinstance(sessions, dict) else []:
            session_tab = getattr(session, "tab", None)
            session_id = _tab_id(session_tab)
            if session_tab is tab or (wanted_id and session_id == wanted_id):
                yield session
    except Exception:
        return


def set_codex_workflow_reuse_hint(enabled: bool) -> None:
    install_codex_workflow_reuse_policy()
    try:
        tab = _find_chatgpt_tab()
    except ChatGPTWebModeError:
        return
    flag = bool(enabled)
    raw_id = _tab_id(tab)
    if raw_id:
        with _REUSE_TAB_IDS_LOCK:
            if flag:
                _REUSE_TAB_IDS.add(raw_id)
            else:
                _REUSE_TAB_IDS.discard(raw_id)
    try:
        setattr(tab, "_uwa_codex_reuse_conversation", flag)
    except Exception:
        pass
    for session in _matching_tab_sessions(tab):
        try:
            setattr(session, "_codex_web_affinity_reuse", flag)
        except Exception:
            pass


__all__ = [
    "WebConversationBinding",
    "affinity_enabled",
    "affinity_status",
    "bind_response_to_conversation",
    "current_chatgpt_conversation_path",
    "ensure_chatgpt_conversation",
    "install_codex_workflow_reuse_policy",
    "resolve_conversation_binding",
    "set_codex_workflow_reuse_hint",
]
