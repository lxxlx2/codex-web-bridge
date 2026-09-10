"""API package for the standalone Codex Web Bridge.

Keep package import side effects minimal. The legacy aggregate ``router`` remains
available lazily for compatibility, while direct imports such as
``app.api.codex_responses_v2`` no longer pull every generic UWA route into the
standalone runtime.
"""

from __future__ import annotations

from typing import Any

__all__ = ["router"]


def __getattr__(name: str) -> Any:
    if name == "router":
        from app.api.routes import router

        return router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
