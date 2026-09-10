"""Minimal FastAPI entrypoint for Codex Web Bridge standalone.

The standalone service exposes the Codex Responses/model surfaces plus a small
health endpoint. Generic UWA dashboards, provider APIs and administration routes
are deliberately outside this entrypoint.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI

from app.api.standalone_routes import router as codex_router
from app.core import get_browser
from app.services.request_manager import request_manager


PROJECT_ROOT = Path(__file__).resolve().parent


def _version() -> str:
    try:
        value = (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        return value or "0.0.0-dev"
    except OSError:
        return "0.0.0-dev"


def _request_status() -> Dict[str, Any]:
    try:
        raw = request_manager.get_status() or {}
        return dict(raw) if isinstance(raw, dict) else {}
    except Exception:
        return {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    try:
        browser = get_browser(auto_connect=False)
        await asyncio.to_thread(browser.close)
    except Exception:
        pass


app = FastAPI(
    title="Codex Web Bridge",
    version=_version(),
    description="Local Responses bridge between Codex Desktop/CLI and ChatGPT Web.",
    lifespan=lifespan,
)
app.include_router(codex_router)


@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "service": "codex-web-bridge",
        "version": _version(),
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
async def health() -> Dict[str, Any]:
    browser = get_browser(auto_connect=False)
    browser_status = await asyncio.to_thread(browser.health_check)
    if not isinstance(browser_status, dict):
        browser_status = {"status": "unhealthy", "connected": False}

    request_status = _request_status()
    running_count = int(request_status.get("running_count", 0) or 0)
    browser_connected = browser_status.get("connected") is True

    return {
        "service": "healthy" if browser_connected else "degraded",
        "version": _version(),
        "browser": browser_status,
        "running_count": running_count,
        "request_manager": request_status,
    }
