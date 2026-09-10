#!/usr/bin/env python3
"""Self-contained launcher for Codex Web Bridge standalone.

The launcher creates a repository-local virtual environment when needed,
installs the pinned standalone requirements when they change, loads optional
``.env`` values, enforces the local-only bind default, and then replaces itself
with Uvicorn. It intentionally contains no updater or generic UWA dashboard
bootstrap logic.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import subprocess
import sys
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
REQUIREMENTS_STAMP = VENV_DIR / ".requirements.sha256"


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _requirements_digest() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def _ensure_venv() -> Path:
    python = _venv_python()
    if not python.exists():
        print(f"[setup] creating virtual environment: {VENV_DIR}", flush=True)
        venv.EnvBuilder(with_pip=True).create(VENV_DIR)

    digest = _requirements_digest()
    installed = ""
    try:
        installed = REQUIREMENTS_STAMP.read_text(encoding="utf-8").strip()
    except OSError:
        pass

    if installed != digest:
        print("[setup] installing standalone requirements", flush=True)
        result = subprocess.run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(REQUIREMENTS)],
            cwd=str(ROOT),
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"dependency installation failed with exit code {result.returncode}")
        REQUIREMENTS_STAMP.write_text(digest + "\n", encoding="utf-8")

    return python


def _loopback_host(value: str) -> bool:
    host = str(value or "").strip()
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main() -> int:
    os.chdir(ROOT)
    _load_env(ROOT / ".env")

    os.environ.setdefault("APP_HOST", "127.0.0.1")
    os.environ.setdefault("APP_PORT", "8199")
    os.environ.setdefault("BROWSER_PORT", "9222")
    os.environ.setdefault("CORS_ENABLED", "false")
    os.environ.setdefault("AUTH_ENABLED", "false")
    os.environ.setdefault("DASHBOARD_ENABLED", "false")
    os.environ.setdefault("UWA_CODEX_WEB_MODE_ENABLED", "true")
    os.environ.setdefault("UWA_CODEX_WEB_MODE_STRICT", "true")
    os.environ.setdefault("UWA_CODEX_REASONING_DEFAULT", "high")

    host = str(os.environ.get("APP_HOST") or "127.0.0.1").strip()
    if not _loopback_host(host):
        raise RuntimeError(
            "standalone release only permits loopback APP_HOST by default; "
            "use 127.0.0.1 or localhost"
        )

    try:
        port = int(str(os.environ.get("APP_PORT") or "8199").strip())
    except ValueError as exc:
        raise RuntimeError("APP_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("APP_PORT must be between 1 and 65535")

    python = _ensure_venv()
    argv = [
        str(python),
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        host,
        "--port",
        str(port),
        "--log-level",
        str(os.environ.get("LOG_LEVEL") or "info").lower(),
    ]
    print(f"[start] Codex Web Bridge listening on http://{host}:{port}", flush=True)
    os.execve(str(python), argv, os.environ.copy())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"[start] failed: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
