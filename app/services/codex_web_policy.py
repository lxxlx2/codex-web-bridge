"""Pragmatic verification policy for the Codex -> ChatGPT web bridge.

The ChatGPT UI does not always expose the selected model or Temporary Chat
state in the DOM.  The reasoning selector is considerably more stable.  On
eligible paid ChatGPT plans, OpenAI documents Medium/High as GPT-5.6 Sol modes.
For the configured GPT-5.6 Sol target we therefore accept a verified Medium or
High UI state as model verification, while still recording whether the model
label itself was directly visible.

Temporary Chat remains best-effort by default so a DOM change cannot take the
entire coding bridge offline.  Set UWA_CODEX_TEMPORARY_CHAT_STRICT=true to make
its verification mandatory again.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from app.services.chatgpt_web_mode import (
    ChatGPTWebModeError,
    _ensure_model,
    _ensure_reasoning,
    _ensure_temporary_chat,
    _find_chatgpt_tab,
    default_reasoning_effort,
    inspect_chatgpt_web_mode,
    target_web_model,
    temporary_chat_enabled,
    web_mode_enabled,
    web_mode_strict,
)
from app.services.chatgpt_web_prepare import prepare_chatgpt_fresh_composer


_REASONING_ALIASES = {
    "ultra": "high",
    "xhigh": "high",
    "extra-high": "high",
    "extra_high": "high",
    "extra high": "high",
    "max": "high",
}
_SUPPORTED_REASONING = {"medium", "high"}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def temporary_chat_strict() -> bool:
    return _env_bool("UWA_CODEX_TEMPORARY_CHAT_STRICT", False)


def normalize_codex_reasoning(value: Any) -> str:
    effort = ""
    if isinstance(value, dict):
        effort = str(value.get("effort") or "").strip().lower()
    else:
        effort = str(value or "").strip().lower()

    if not effort:
        effort = default_reasoning_effort()

    effort = _REASONING_ALIASES.get(effort, effort)
    if effort not in _SUPPORTED_REASONING:
        raise ChatGPTWebModeError(
            f"unsupported Codex reasoning effort: {effort}; supported=medium,high"
        )
    return effort


def _is_sol_target(value: Any) -> bool:
    return str(value or "").strip().casefold() == "gpt-5.6 sol".casefold()


def evaluate_codex_web_state(state: Dict[str, Any], effort: str) -> Dict[str, Any]:
    """Evaluate current browser state without changing the page."""
    desired_model = target_web_model()
    actual_reasoning = str(state.get("reasoning") or "").strip().lower() or None
    reasoning_ok = actual_reasoning == effort

    direct_model_ok = (
        str(state.get("model") or "").strip().casefold()
        == desired_model.strip().casefold()
    )
    mapped_model_ok = bool(_is_sol_target(desired_model) and reasoning_ok)
    model_ok = direct_model_ok or mapped_model_ok

    temp_requested = temporary_chat_enabled()
    temp_verified = state.get("temporary_chat") is True
    temp_required = bool(temp_requested and temporary_chat_strict())
    temp_ok = temp_verified if temp_required else True

    errors: list[str] = []
    if not reasoning_ok:
        errors.append(f"reasoning expected={effort!r} actual={state.get('reasoning')!r}")
    if not model_ok:
        errors.append(f"model expected={desired_model!r} actual={state.get('model')!r}")
    if temp_required and not temp_verified:
        errors.append(
            f"temporary_chat expected=True actual={state.get('temporary_chat')!r}"
        )

    verified = not errors
    result = dict(state)
    result.update(
        {
            "model": desired_model if mapped_model_ok and not state.get("model") else state.get("model"),
            "requested_reasoning": effort,
            "reasoning_verified": reasoning_ok,
            "model_verified": model_ok,
            "model_verification": (
                "dom" if direct_model_ok else "official-reasoning-mapping" if mapped_model_ok else None
            ),
            "temporary_chat_requested": temp_requested,
            "temporary_chat_verified": temp_verified,
            "temporary_chat_strict": temp_required,
            "verified": verified,
            "verification_errors": errors,
        }
    )
    return result


def inspect_codex_web_mode_status(reasoning: Any = None) -> Dict[str, Any]:
    if not web_mode_enabled():
        return {"enabled": False, "verified": False}

    effort = normalize_codex_reasoning(reasoning)
    state = inspect_chatgpt_web_mode()
    result = evaluate_codex_web_state(state, effort)
    result["enabled"] = True
    return result


def prepare_and_verify_codex_web_mode(reasoning: Any = None) -> Dict[str, Any]:
    """Prepare a fresh composer and require a verified reasoning mode.

    Model DOM visibility and Temporary Chat visibility are treated separately:
    - GPT-5.6 Sol can be verified through a confirmed Medium/High reasoning mode.
    - Temporary Chat is attempted, reported, and only blocking when explicitly
      configured strict.
    """
    if not web_mode_enabled():
        return {"enabled": False, "verified": False}

    effort = normalize_codex_reasoning(reasoning)
    preparation = prepare_chatgpt_fresh_composer()
    tab = _find_chatgpt_tab()

    if temporary_chat_enabled():
        _ensure_temporary_chat(tab)

    # Keep the direct model switch attempt as a best-effort improvement.  Its
    # DOM verification is no longer required when the paid-plan reasoning mode
    # itself proves the GPT-5.6 Sol route.
    _ensure_model(tab, target_web_model())
    reasoning_selected = _ensure_reasoning(tab, effort)

    state = inspect_chatgpt_web_mode(tab)
    if reasoning_selected and state.get("reasoning") is None:
        state["reasoning"] = effort
        state["reasoning_verification"] = "selected-menu-state"

    result = evaluate_codex_web_state(state, effort)
    result.update(
        {
            "enabled": True,
            "composer_preparation": preparation,
        }
    )

    if result["verified"]:
        return result

    detail = "; ".join(result.get("verification_errors") or [])
    if web_mode_strict():
        raise ChatGPTWebModeError(f"ChatGPT Web mode verification failed: {detail}")
    return result
