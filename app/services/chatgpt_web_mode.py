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
const modelRow = selectedRows.find((row) => modelPattern.test(combined(row)))
  || visibleRows.find((row) =>
    !['option', 'menuitem', 'menuitemradio'].includes(low(row.el.getAttribute('role')))
    && modelPattern.test(combined(row))
  );

const highPattern = /^(high|高)$/i;
const mediumPattern = /^(medium|中)$/i;
const reasoningRow = selectedRows.find((row) => highPattern.test(row.text) || highPattern.test(row.aria) || mediumPattern.test(row.text) || mediumPattern.test(row.aria))
  || visibleRows.find((row) => highPattern.test(row.text) || highPattern.test(row.aria) || mediumPattern.test(row.text) || mediumPattern.test(row.aria));
const sliders = Array.from(document.querySelectorAll('[role="menuitem"][aria-label="强度"] [role="slider"], [role="menuitem"][aria-label="Reasoning intensity"] [role="slider"]'))
  .filter(visible);
const slider = sliders.length === 1 && sliders[0].getAttribute('aria-valuemin') === '0'
  && sliders[0].getAttribute('aria-valuemax') === '2' ? sliders[0] : null;

const tempRows = Array.from(document.querySelectorAll('button,[role="button"]')).map((el) => ({
  visible: visible(el),
  text: norm(el.innerText || el.textContent),
  aria: norm(el.getAttribute('aria-label')),
})).filter((row) => row.visible && (row.aria || row.text));
const enableTemp = tempRows.find((row) => /开启临时聊天|启用临时聊天|enable temporary chat/i.test(`${row.text} ${row.aria}`));
const startTemp = tempRows.find((row) => /^(临时聊天|temporary chat)$/i.test(row.aria));
const disableTemp = tempRows.find((row) => /关闭临时聊天|停用临时聊天|disable temporary chat/i.test(`${row.text} ${row.aria}`));
let temp = null;
if (disableTemp) temp = true;
else if (enableTemp || startTemp) temp = false;

let reasoning = null;
if (reasoningRow) {
  const value = norm(reasoningRow.text || reasoningRow.aria);
  if (highPattern.test(value)) reasoning = 'high';
  else if (mediumPattern.test(value)) reasoning = 'medium';
}
if (!reasoning && slider) {
  const value = slider.getAttribute('aria-valuenow');
  if (value === '2') reasoning = 'high';
  else if (value === '1') reasoning = 'medium';
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
const controls = Array.from(document.querySelectorAll('button,[role="button"],[role="option"],[role="menuitem"],[role="menuitemradio"],[role="slider"],[aria-label],[data-testid]'))
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
    pressed: norm(el.getAttribute('aria-pressed')).slice(0, 20),
    value: norm(el.getAttribute('aria-valuenow')).slice(0, 20),
    value_min: norm(el.getAttribute('aria-valuemin')).slice(0, 20),
    value_max: norm(el.getAttribute('aria-valuemax')).slice(0, 20),
  }))
  .filter((item) => item.role === 'slider' || relevant.test(`${item.text} ${item.aria} ${item.testid} ${item.role}`))
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
const ariaExact = values(spec.aria_exact);
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
    if (ariaExact.length && ariaExact.includes(aria)) return true;
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


_MODEL_MENU_STATE_JS = r"""
const buttons = Array.from(document.querySelectorAll('button[aria-haspopup="menu"]'));
const trigger = buttons.find((el) => /选择.*模型|select.*model|choose.*model/i.test(el.getAttribute('aria-label') || ''));
if (!trigger) return null;
return trigger.getAttribute('aria-expanded') === 'true' ? 'open' : 'closed';
"""


_REASONING_SLIDER_JS = r"""
const visible = (el) => {
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
};
const sliders = Array.from(document.querySelectorAll('[role="menuitem"][aria-label="强度"] [role="slider"], [role="menuitem"][aria-label="Reasoning intensity"] [role="slider"]')).filter(visible);
if (sliders.length !== 1) return null;
const slider = sliders[0];
if (slider.getAttribute('aria-valuemin') !== '0' || slider.getAttribute('aria-valuemax') !== '2') return null;
const value = slider.getAttribute('aria-valuenow');
return ['0', '1', '2'].includes(value) ? Number(value) : null;
"""


def _run_js(tab: Any, script: str, *args: Any) -> Any:
    try:
        return tab.run_js(script, *args)
    except Exception as exc:
        raise ChatGPTWebModeError(f"controlled browser JavaScript failed: {exc}") from exc


def _click(tab: Any, **spec: Any) -> Dict[str, Any]:
    result = _run_js(tab, _CLICK_JS, json.dumps(spec, ensure_ascii=False))
    return result if isinstance(result, dict) else {"clicked": False}


def _model_menu_state(tab: Any) -> Optional[str]:
    state = _run_js(tab, _MODEL_MENU_STATE_JS)
    return state if state in {"open", "closed"} else None


def _open_model_menu(tab: Any) -> bool:
    if _model_menu_state(tab) == "open":
        return True
    clicked = _click(
        tab,
        contains_texts=["选择模型", "模型", "select model", "choose model"],
        aria_contains=["model", "模型"],
        testid_contains=["model"],
    ).get("clicked")
    if not clicked:
        return False
    time.sleep(0.12)
    return _model_menu_state(tab) == "open"


def _close_model_menu(tab: Any) -> bool:
    if _model_menu_state(tab) == "closed":
        return True
    try:
        tab.actions.key_down("ESCAPE").key_up("ESCAPE")
    except Exception as exc:
        raise ChatGPTWebModeError(f"controlled browser keyboard action failed: {exc}") from exc
    time.sleep(0.08)
    return _model_menu_state(tab) == "closed"


def inspect_chatgpt_web_mode(tab: Optional[Any] = None) -> Dict[str, Any]:
    target = tab or _find_chatgpt_tab()
    result = _run_js(target, _STATE_JS)
    state = result if isinstance(result, dict) else {}
    if state.get("model") is None or state.get("reasoning") is None:
        # The current ChatGPT model trigger can show only its mode name while
        # the chosen model and reasoning intensity remain inside its menu.
        # Open that menu for a read-only verification, then close it again.
        was_open = _model_menu_state(target) == "open"
        if _open_model_menu(target):
            expanded = {}
            for _ in range(4):
                time.sleep(0.12)
                candidate = _run_js(target, _STATE_JS)
                if isinstance(candidate, dict):
                    expanded = candidate
                    if candidate.get("model") is not None and candidate.get("reasoning") is not None:
                        break
            if not was_open:
                if not _close_model_menu(target):
                    raise ChatGPTWebModeError("controlled model menu did not close")
            if isinstance(expanded, dict):
                state = dict(state)
                if state.get("model") is None:
                    state["model"] = expanded.get("model")
                if state.get("reasoning") is None:
                    state["reasoning"] = expanded.get("reasoning")
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
    if state.get("temporary_chat") is not False:
        return
    clicked = _click(
        tab,
        contains_texts=["开启临时聊天", "启用临时聊天", "enable temporary chat"],
        aria_exact=["临时聊天", "temporary chat"],
        aria_contains=["开启临时聊天", "启用临时聊天", "enable temporary chat"],
        testid_contains=["temporary", "temp-chat"],
    ).get("clicked")
    if clicked:
        # Starting a temporary chat can rebuild the model controls. Wait for
        # the new mode label and trigger before selecting a model or effort.
        ready = 0
        for _ in range(15):
            time.sleep(0.2)
            current = _run_js(tab, _STATE_JS)
            if isinstance(current, dict) and current.get("temporary_chat") is True and _model_menu_state(tab) == "closed":
                ready += 1
                if ready == 2:
                    break
            else:
                ready = 0


def _ensure_model(tab: Any, desired_model: str) -> None:
    state = inspect_chatgpt_web_mode(tab)
    if str(state.get("model") or "").casefold() == desired_model.casefold():
        return

    opened = _open_model_menu(tab)
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
    return _open_model_menu(tab)


def _ensure_reasoning(tab: Any, effort: str) -> bool:
    state = inspect_chatgpt_web_mode(tab)
    if state.get("reasoning") == effort:
        return True

    if not _open_reasoning_menu(tab):
        return False
    target_value = 2 if effort == "high" else 1
    current = _run_js(tab, _REASONING_SLIDER_JS)
    if type(current) is not int:
        _close_model_menu(tab)
        return False
    for _ in range(2):
        if current == target_value:
            break
        direction = "RIGHT" if current < target_value else "LEFT"
        try:
            tab.ele('css:[role="menuitem"][aria-label="强度"] [role="slider"], [role="menuitem"][aria-label="Reasoning intensity"] [role="slider"]').click()
            tab.actions.key_down(direction).key_up(direction)
        except Exception as exc:
            raise ChatGPTWebModeError(f"controlled browser keyboard action failed: {exc}") from exc
        time.sleep(0.12)
        next_value = _run_js(tab, _REASONING_SLIDER_JS)
        if type(next_value) is not int or next_value != current + (1 if direction == "RIGHT" else -1):
            _close_model_menu(tab)
            return False
        current = next_value
    verified = current == target_value
    return verified and _close_model_menu(tab)


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
    if state.get("reasoning") != effort and (state.get("reasoning") is not None or not reasoning_verified):
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
