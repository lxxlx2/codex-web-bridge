"""Security policy for the standalone Codex Web Bridge runtime."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

_TRUTHY = {"1", "true", "yes", "on"}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def _env_bool(name: str, default: bool = False, environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in _TRUTHY


def _read_dotenv(path: str | Path = ".env") -> dict[str, str]:
    result: dict[str, str] = {}
    env_path = Path(path)
    if not env_path.exists() or not env_path.is_file():
        return result
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            result[key] = value
    return result


def ensure_safe_defaults() -> None:
    defaults = {
        "APP_HOST": "127.0.0.1",
        "APP_PORT": "8199",
        "APP_DEBUG": "false",
        "LOG_LEVEL": "INFO",
        "AUTH_ENABLED": "false",
        "DASHBOARD_AUTH_ENABLED": "false",
        "CORS_ENABLED": "false",
        "CORS_ORIGINS": "http://127.0.0.1:8199",
        "BROWSER_PORT": "9222",
        "BROWSER_PROFILE_DIR": "chrome_profile",
        "CMD_ALLOW_UNSAFE_PYTHON_COMMANDS": "false",
        "AUTO_UPDATE_ENABLED": "false",
        "PROFILE_CLEAN_ENABLED": "false",
        "SCHEDULED_RESTART_ENABLED": "false",
        "PROXY_ENABLED": "false",
        "PIP_MIRROR_URL": "https://pypi.org/simple",
        "UWAPI_ALLOW_REMOTE": "false",
        "UWAPI_ALLOW_UPSTREAM_AUTO_UPDATE": "false",
        "TOOL_CALLING_CLIENT_WORKSPACE_REPAIR": "true",
        "TOOL_CALLING_PROMPT_PADDING_ENABLED": "false",
        "TOOL_CALLING_PROMPT_PADDING_OBFUSCATE": "false",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def effective_startup_environment(dotenv_path: str | Path = ".env") -> dict[str, str]:
    env = dict(os.environ)
    env.update(_read_dotenv(dotenv_path))
    return env


def _token_is_strong(value: str) -> bool:
    return len(str(value or "").strip()) >= 32


def validate_runtime_security(environ: Mapping[str, str] | None = None) -> None:
    env = os.environ if environ is None else environ
    errors: list[str] = []
    if _env_bool("CMD_ALLOW_UNSAFE_PYTHON_COMMANDS", False, env):
        errors.append("CMD_ALLOW_UNSAFE_PYTHON_COMMANDS must remain false")
    if _env_bool("AUTO_UPDATE_ENABLED", False, env) and not _env_bool(
        "UWAPI_ALLOW_UPSTREAM_AUTO_UPDATE", False, env
    ):
        errors.append(
            "AUTO_UPDATE_ENABLED requires UWAPI_ALLOW_UPSTREAM_AUTO_UPDATE=true; manual upstream sync is recommended"
        )
    if _env_bool("CORS_ENABLED", False, env):
        origins = [item.strip() for item in str(env.get("CORS_ORIGINS", "") or "").split(",") if item.strip()]
        if not origins or "*" in origins:
            errors.append("CORS_ORIGINS must be an explicit allow-list")
    host = str(env.get("APP_HOST", "127.0.0.1") or "").strip().lower()
    if host not in _LOOPBACK_HOSTS:
        if not _env_bool("UWAPI_ALLOW_REMOTE", False, env):
            errors.append("set UWAPI_ALLOW_REMOTE=true to explicitly allow non-loopback binding")
        if _env_bool("APP_DEBUG", False, env):
            errors.append("APP_DEBUG must be false for non-loopback binding")
        if not _env_bool("AUTH_ENABLED", False, env):
            errors.append("AUTH_ENABLED must be true for non-loopback binding")
        elif not _token_is_strong(str(env.get("AUTH_TOKEN", ""))):
            errors.append("AUTH_TOKEN must contain at least 32 characters")
        if not _env_bool("DASHBOARD_AUTH_ENABLED", False, env):
            errors.append("DASHBOARD_AUTH_ENABLED must be true for non-loopback binding")
        else:
            dashboard_token = str(env.get("DASHBOARD_AUTH_TOKEN", "") or "").strip()
            auth_token = str(env.get("AUTH_TOKEN", "") or "").strip()
            if not _token_is_strong(dashboard_token):
                errors.append("DASHBOARD_AUTH_TOKEN must contain at least 32 characters")
            elif dashboard_token == auth_token:
                errors.append("DASHBOARD_AUTH_TOKEN must differ from AUTH_TOKEN")
    if errors:
        raise RuntimeError("Unsafe Codex Web Bridge configuration: " + "; ".join(errors))
