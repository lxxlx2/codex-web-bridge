"""Network timeout tuning for the Codex -> ChatGPT web bridge.

GPT-5.6 Sol High can spend substantially longer than a normal chat request before
emitting visible answer text.  UWA's generic ChatGPT network monitor is tuned for
interactive chat and can therefore classify a healthy High-reasoning request as
an empty/silent stream too early.

This module installs an idempotent, ChatGPT-only NetworkMonitor constructor
wrapper.  It copies the per-request stream config and raises only the first
visible-content and post-content silence budgets.  Other sites/parsers are left
untouched and the existing hard timeout remains authoritative.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Dict


_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_ORIGINAL_INIT = None


def _bounded_env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    try:
        value = float(raw) if raw not in (None, "") else float(default)
    except (TypeError, ValueError):
        value = float(default)
    return min(max(value, minimum), maximum)


def codex_chatgpt_first_content_timeout() -> float:
    return _bounded_env_float(
        "UWA_CODEX_CHATGPT_FIRST_CONTENT_TIMEOUT_SEC",
        180.0,
        30.0,
        600.0,
    )


def codex_chatgpt_post_content_silence_timeout() -> float:
    return _bounded_env_float(
        "UWA_CODEX_CHATGPT_POST_CONTENT_SILENCE_SEC",
        60.0,
        15.0,
        300.0,
    )


def _parser_id(parser: Any) -> str:
    try:
        return str(parser.get_id() or "").strip().lower()
    except Exception:
        return parser.__class__.__name__.strip().lower()


def _tuned_stream_config(stream_config: Any, parser: Any) -> Any:
    if _parser_id(parser) != "chatgpt":
        return stream_config

    config: Dict[str, Any] = dict(stream_config or {})
    network: Dict[str, Any] = dict(config.get("network") or {})

    first_budget = codex_chatgpt_first_content_timeout()
    post_budget = codex_chatgpt_post_content_silence_timeout()

    try:
        current_first = float(network.get("first_content_timeout") or 0)
    except (TypeError, ValueError):
        current_first = 0.0
    try:
        current_post = float(network.get("post_content_silence_threshold") or 0)
    except (TypeError, ValueError):
        current_post = 0.0

    network["first_content_timeout"] = max(current_first, first_budget)
    network["post_content_silence_threshold"] = max(current_post, post_budget)
    config["network"] = network
    return config


def install_codex_chatgpt_network_tuning() -> bool:
    """Install ChatGPT-only timeout tuning once per process.

    Returns True when the wrapper is installed by this call and False when it
    was already installed.  No browser state, account data, or request content
    is inspected.
    """

    global _INSTALLED, _ORIGINAL_INIT
    if _INSTALLED:
        return False

    with _INSTALL_LOCK:
        if _INSTALLED:
            return False

        from app.core.network_monitor import NetworkMonitor

        original_init = NetworkMonitor.__init__
        _ORIGINAL_INIT = original_init

        def tuned_init(
            self,
            tab,
            formatter,
            parser,
            stop_checker=None,
            stream_config=None,
            event_handler=None,
            result_handler=None,
            image_config=None,
        ):
            return original_init(
                self,
                tab,
                formatter,
                parser,
                stop_checker=stop_checker,
                stream_config=_tuned_stream_config(stream_config, parser),
                event_handler=event_handler,
                result_handler=result_handler,
                image_config=image_config,
            )

        tuned_init.__name__ = getattr(original_init, "__name__", "__init__")
        tuned_init.__doc__ = getattr(original_init, "__doc__", None)
        NetworkMonitor.__init__ = tuned_init
        _INSTALLED = True
        return True


__all__ = [
    "codex_chatgpt_first_content_timeout",
    "codex_chatgpt_post_content_silence_timeout",
    "install_codex_chatgpt_network_tuning",
]
