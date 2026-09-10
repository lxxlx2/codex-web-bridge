"""ChatGPT web-mode control for the Codex browser bridge.

This module keeps the browser-side execution target explicit. Codex continues
using the logical ``chatgpt`` route id, while UWA verifies the controlled
ChatGPT tab is configured for the expected web model and reasoning level before
forwarding a Responses request.

The implementation intentionally uses only the project-controlled browser tab.
It never reads cookies, local storage, account identifiers, conversation text,
or other private page data.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from app.core import get_browser
from app.core.config import get_logger


logger = get_logger("CODEX.WEBMODE")

DEFAULT_WEB_MODEL = "GPT-5.6 Sol"
DEFAULT_REASONING = "high"
_SUPPORTED_REASONING = {"medium", "high"}


class ChatGPTWebModeError(RuntimeError):
    """Raised when the controlled ChatGPT tab cannot be verified safely."""


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def web_mode_enabled() -> bool:
    return _env_bool("UWA_CODEX_WEB_MODE_ENABLED", True)


def web_mode_strict() -> bool:
    return _env_bool("UWA_CODEX_WEB_MODE_STRICT", True)


def temporary_chat_enabled() -> bool:
    return _env_bool("UWA_CODEX_TEMPORARY_CHAT", True)


def target_web_model() -> str:
    value = str(os.getenv("UWA_CODEX_WEB_MODEL") or DEFAULT_WEB_MODEL).strip()
    return value or DEFAULT_WEB_MODEL


def default_reasoning_effort() -> str:
    value = str(os.getenv("UWA_CODEX_REASONING_DEFAULT") or DEFAULT_REASONING).strip().lower()
    return value if value in _SUPPORTED_REASONING else DEFAULT_REASONING


def normalize_reasoning_effort(value: Any) -> str:
    effort = ""
    if isinstance(value, dict):
        effort = str(value.get("effort") or "").strip().lower()
    else:
        effort = str(value or "").strip().lower()
    if not effort:
        return default_reasoning_effort()
    if effort not in _SUPPORTED_REASONING:
        raise ChatGPTWebModeError(
            f"unsupported Codex reasoning effort: {effort}; supported=medium,high"
        )
    return effort


def _tab_url(tab: Any) -> str:
    try:
        return str(getattr(tab, "url", "") or "")
    except Exception:
        return ""


def _is_chatgpt_url(url: str) -> bool:
    try:
        host = (urlparse(str(url or "")).hostname or "").lower()
    except Exception:
        host = ""
    return host in {"chatgpt.com", "www.chatgpt.com"}


def _find_chatgpt_tab() -> Any:
    browser = get_browser(auto_connect=False)
    health = browser.health_check()
    if not isinstance(health, dict) or not health.get("connected"):
        raise ChatGPTWebModeError("controlled browser is not connected")

    matches = [tab for tab in list(browser.get_tabs() or []) if _is_chatgpt_url(_tab_url(tab))]
    if not matches:
        raise ChatGPTWebModeError("no controlled chatgpt.com tab found")
    if len(matches) > 1 and web_mode_strict():
        raise ChatGPTWebModeError(
            "multiple controlled chatgpt.com tabs found; keep exactly one tab in strict mode"
        )
    return matches[0]


_STATE_JS = r"""
const visible = (el) => {
  if (!el) return false;
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
};
const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim();
const low = (value) => norm(value).toLowerCase();
const nodes = Array.from(document.querySelectorAll('button,[role="button"],[role="option"],[role="menuitem"],[role="menuitemradio"],[aria-checked],[data-state]'));
const rows = nodes.map((el) => ({
  el,
  visible: visible(el),
  text: norm(el.innerText || el.textContent),
  aria: norm(el.getAttribute('aria-label')),
  checked: low(el.getAttribute('aria-checked')) === 'true' || low(el.getAttribute('data-state')) === 'checked' || low(el.getAttribute('data-selected')) === 'true',
}));

const selectedRows = rows.filter((row) => row.checked);
const visibleRows = rows.filter((row) => row.visible);
const combined = (row) => norm(`${row.text} ${row.aria}`);

const modelPattern = /gpt\s*[- ]?5\.6\s*sol/i;
const modelRow = selectedRows.find((row) => modelPattern.test(combined(row))) || visibleRows.find((row) => modelPattern.test(combined(row)));

const highPattern = /^(high|高)$/i;
const mediumPattern = /^(medium|中)$/i;
const reasoningRow = selectedRows.find((row) => highPattern.test(row.text) || highPattern.test(row.aria) || mediumPattern.test(row.text) || mediumPattern.test(row.aria))
  || visibleRows.find((row) => highPattern.test(row.text) || highPattern.test(row.aria) || mediumPattern.test(row.text) || mediumPattern.test(row.aria));

const tempRows = Array.from(document.querySelectorAll('button,[role="button"]')).map((el) => ({
  text: norm(el.innerText || el.textContent),
  aria: norm(el.getAttribute('aria-label')),
}));
const enableTemp = tempRows.find((row) => /开启临时聊天|启用临时聊天|enable temporary chat/i.test(`${row.text} ${row.aria}`));
const disableTemp = tempRows.find((row) => /关闭临时聊天|停用临时聊天|disable temporary chat/i.test(`${row.text} ${row.aria}`));
let temp = null;
if (disableTemp) temp = true;
else if (enableTemp) temp = false;

let reasoning = null;
if (reasoningRow) {
  const value = norm(reasoningRow.text || reasoningRow.aria);
  if (highPattern.test(value)) reasoning = 'high';
  else if (mediumPattern.test(value)) reasoning = 'medium';
}

return {
  model: modelRow ? 'GPT-5.6 Sol' : null,
  reasoning,
  temporary_chat: temp,
};
"""


_DIAGNOSTICS_JS = r"""
const visible = (el) => {
  if (!el) return false;
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  return !!style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
};
const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim();
const relevant = /gpt|model|模型|reason|thinking|思考|high|medium|临时|temporary|^高$|^中$/i;
const controls = Array.from(document.querySelectorAll('button,[role="button"],[role="option"],[role="menuitem"],[role="menuitemradio"],[aria-label],[data-testid]'))
  .filter((el) => visible(el))
  .map((el) => ({
    tag: String(el.tagName || '').toLowerCase(),
    role: norm(el.getAttribute('role')),
    text: norm(el.innerText || el.textContent).slice(0, 120),
    aria: norm(el.getAttribute('aria-label')).slice(0, 120),
    testid: norm(el.getAttribute('data-testid')).slice(0, 120),
    state: norm(el.getAttribute('data-state')).slice(0, 40),
    checked: norm(el.getAttribute('aria-checked')).slice(0, 20),
    expanded: norm(el.getAttribute('aria-expanded')).slice(0, 20),
    haspopup: norm(el.getAttribute('aria-haspopup')).slice(0, 40),
  }))
  .filter((item) => relevant.test(`${item.text} ${item.aria} ${item.testid} ${item.role}`))
  .slice(0, 80);

return {
  page: {
    host: location.hostname,
    pathname: location.pathname.slice(0, 180),
    lang: document.documentElement.lang || '',
  },
  exact_selectors: {
    temp_enable_exact: !!document.querySelector('button[aria-label="开启临时聊天"]'),
    temp_disable_exact: !!document.querySelector('button[aria-label="关闭临时聊天"]'),
    prompt: !!document.querySelector('#prompt-textarea'),
    send: !!document.querySelector('[data-testid="send-button"]'),
  },
  controls,
};
"""


_CLICK_JS = r"""
const spec = JSON.parse(arguments[0]);
const visible = (el) => {
  if (!el) return false;
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
};
const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim();
const low = (value) => norm(value).toLowerCase();
const values = (items) => (items || []).map((item) => low(item));
const exact = values(spec.exact_texts);
const contains = values(spec.contains_texts);
const starts = values(spec.starts_with_texts);
const ariaContains = values(spec.aria_contains);
const testidContains = values(spec.testid_contains);
const roles = new Set(values(spec.roles));

const candidates = Array.from(document.querySelectorAll('button,[role="button"],[role="option"],[role="menuitem"],[role="menuitemradio"]'))
  .filter(visible)
  .filter((el) => {
    const text = low(el.innerText || el.textContent);
    const aria = low(el.getAttribute('aria-label'));
    const testid = low(el.getAttribute('data-testid'));
    const role = low(el.getAttribute('role'));
    if (roles.size && !roles.has(role)) return false;
    if (exact.length && exact.includes(text)) return true;
    if (contains.length && contains.some((item) => text.includes(item) || aria.includes(item))) return true;
    if (starts.length && starts.some((item) => text.startsWith(item))) return true;
    if (ariaContains.length && ariaContains.some((item) => aria.includes(item))) return true;
    if (testidContains.length && testidContains.some((item) => testid.includes(item))) return true;
    return false;
  });

const target = candidates[0];
if (!target) return {clicked: false};
target.click();
return {
  clicked: true,
  text: norm(target.innerText || target.textContent).slice(0, 80),
  aria: norm(target.getAttribute('aria-label')).slice(0, 80),
  testid: norm(target.getAttribute('data-testid')).slice(0, 80),
};
"""


_ESCAPE_JS = r"""
const eventInit = {key: 'Escape', code: 'Escape', keyCode: 27, which: 27, bubbles: true};
(document.activeElement || document.body).dispatchEvent(new KeyboardEvent('keydown', eventInit));
document.dispatchEvent(new KeyboardEvent('keydown', eventInit));
return true;
"""


def _run_js(tab: Any, script: str, *args: Any) -> Any:
    try:
        return tab.run_js(script, *args)
    except Exception as exc:
        raise ChatGPTWebModeError(f"controlled browser JavaScript failed: {exc}") from exc


def _click(tab: Any, **spec: Any) -> Dict[str, Any]:
    result = _run_js(tab, _CLICK_JS, json.dumps(spec, ensure_ascii=False))
    return result if isinstance(result, dict) else {"clicked": False}


def inspect_chatgpt_web_mode(tab: Optional[Any] = None) -> Dict[str, Any]:
    target = tab or _find_chatgpt_tab()
    result = _run_js(target, _STATE_JS)
    state = result if isinstance(result, dict) else {}
    return {
        "model": state.get("model"),
        "reasoning": state.get("reasoning"),
        "temporary_chat": state.get("temporary_chat"),
        "target_model": target_web_model(),
        "target_reasoning_default": default_reasoning_effort(),
        "strict": web_mode_strict(),
    }


def inspect_chatgpt_web_mode_diagnostics(tab: Optional[Any] = None) -> Dict[str, Any]:
    """Return only sanitized model/mode control metadata, never conversation text."""
    target = tab or _find_chatgpt_tab()
    result = _run_js(target, _DIAGNOSTICS_JS)
    payload = result if isinstance(result, dict) else {}
    return {
        "state": inspect_chatgpt_web_mode(target),
        "page": payload.get("page") if isinstance(payload.get("page"), dict) else {},
        "exact_selectors": payload.get("exact_selectors") if isinstance(payload.get("exact_selectors"), dict) else {},
        "controls": payload.get("controls") if isinstance(payload.get("controls"), list) else [],
    }


def _ensure_temporary_chat(tab: Any) -> None:
    if not temporary_chat_enabled():
        return
    state = inspect_chatgpt_web_mode(tab)
    if state.get("temporary_chat") is True:
        return
    clicked = _click(
        tab,
        contains_texts=["开启临时聊天", "启用临时聊天", "enable temporary chat", "temporary chat"],
        aria_contains=["开启临时聊天", "启用临时聊天", "enable temporary chat", "temporary chat"],
        testid_contains=["temporary", "temp-chat"],
    ).get("clicked")
    if clicked:
        time.sleep(0.35)


def _ensure_model(tab: Any, desired_model: str) -> None:
    state = inspect_chatgpt_web_mode(tab)
    if str(state.get("model") or "").casefold() == desired_model.casefold():
        return

    opened = _click(
        tab,
        contains_texts=["选择模型", "模型", "select model", "choose model"],
        aria_contains=["model", "模型"],
        testid_contains=["model"],
    ).get("clicked")
    if opened:
        time.sleep(0.25)

    selected = _click(
        tab,
        exact_texts=[desired_model],
        contains_texts=[desired_model],
        roles=["option", "menuitem", "menuitemradio", "button"],
    ).get("clicked")
    if selected:
        time.sleep(0.35)


def _open_reasoning_menu(tab: Any) -> bool:
    return bool(
        _click(
            tab,
            contains_texts=["思考强度", "reasoning", "thinking"],
            aria_contains=["思考强度", "reasoning", "thinking"],
            testid_contains=["reasoning", "thinking"],
        ).get("clicked")
    )


def _ensure_reasoning(tab: Any, effort: str) -> bool:
    state = inspect_chatgpt_web_mode(tab)
    if state.get("reasoning") == effort:
        return True

    if _open_reasoning_menu(tab):
        time.sleep(0.2)

    label = "高" if effort == "high" else "中"
    english = "High" if effort == "high" else "Medium"
    selected = _click(
        tab,
        exact_texts=[label, english],
        roles=["option", "menuitem", "menuitemradio", "button"],
    ).get("clicked")
    if not selected:
        _run_js(tab, _ESCAPE_JS)
        return False

    time.sleep(0.3)

    if _open_reasoning_menu(tab):
        time.sleep(0.2)
        probe = inspect_chatgpt_web_mode(tab)
        verified = probe.get("reasoning") == effort
        _run_js(tab, _ESCAPE_JS)
        time.sleep(0.1)
        return verified

    return False


def _verification_errors(
    state: Dict[str, Any],
    effort: str,
    *,
    reasoning_verified: bool = False,
) -> list[str]:
    errors: list[str] = []
    desired_model = target_web_model()
    if str(state.get("model") or "").casefold() != desired_model.casefold():
        errors.append(f"model expected={desired_model!r} actual={state.get('model')!r}")
    if state.get("reasoning") != effort and not reasoning_verified:
        errors.append(f"reasoning expected={effort!r} actual={state.get('reasoning')!r}")
    if temporary_chat_enabled() and state.get("temporary_chat") is not True:
        errors.append(f"temporary_chat expected=True actual={state.get('temporary_chat')!r}")
    return errors


def ensure_codex_chatgpt_web_mode(reasoning: Any = None) -> Dict[str, Any]:
    """Apply and verify the configured ChatGPT model/mode for a Codex request."""
    if not web_mode_enabled():
        return {
            "enabled": False,
            "model": None,
            "reasoning": None,
            "temporary_chat": None,
            "verified": False,
        }

    effort = normalize_reasoning_effort(reasoning)
    tab = _find_chatgpt_tab()

    _ensure_temporary_chat(tab)
    _ensure_model(tab, target_web_model())
    reasoning_verified = _ensure_reasoning(tab, effort)

    state = inspect_chatgpt_web_mode(tab)
    if reasoning_verified and state.get("reasoning") is None:
        state["reasoning"] = effort
        state["reasoning_verification"] = "selected-menu-state"

    errors = _verification_errors(
        state,
        effort,
        reasoning_verified=reasoning_verified,
    )
    verified = not errors
    state.update({"enabled": True, "verified": verified, "requested_reasoning": effort})

    if verified:
        logger.info(
            "Codex Web mode verified: "
            f"model={state.get('model')}, reasoning={effort}, temporary_chat={state.get('temporary_chat')}"
        )
        return state

    detail = "; ".join(errors)
    if web_mode_strict():
        raise ChatGPTWebModeError(f"ChatGPT Web mode verification failed: {detail}")

    logger.warning(f"ChatGPT Web mode not fully verified: {detail}")
    return state
