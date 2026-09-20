from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from security_guard import ensure_safe_defaults, validate_runtime_security
from tools.public_repo_safety_check import (
    BROWSER_CONFIG_PRIVATE_PATTERNS,
    PRIVATE_RUNTIME_TEXT_PATTERNS,
)


def test_safe_defaults(monkeypatch):
    for key in (
        "APP_HOST",
        "APP_DEBUG",
        "CORS_ENABLED",
        "CMD_ALLOW_UNSAFE_PYTHON_COMMANDS",
        "AUTO_UPDATE_ENABLED",
        "PROXY_ENABLED",
        "PIP_MIRROR_URL",
        "TOOL_CALLING_CLIENT_WORKSPACE_REPAIR",
        "TOOL_CALLING_PROMPT_PADDING_ENABLED",
        "TOOL_CALLING_PROMPT_PADDING_OBFUSCATE",
    ):
        monkeypatch.delenv(key, raising=False)

    ensure_safe_defaults()

    assert os.environ["APP_HOST"] == "127.0.0.1"
    assert os.environ["APP_DEBUG"] == "false"
    assert os.environ["CORS_ENABLED"] == "false"
    assert os.environ["CMD_ALLOW_UNSAFE_PYTHON_COMMANDS"] == "false"
    assert os.environ["AUTO_UPDATE_ENABLED"] == "false"
    assert os.environ["PROXY_ENABLED"] == "false"
    assert os.environ["PIP_MIRROR_URL"] == "https://pypi.org/simple"
    assert os.environ["TOOL_CALLING_CLIENT_WORKSPACE_REPAIR"] == "true"
    assert os.environ["TOOL_CALLING_PROMPT_PADDING_ENABLED"] == "false"
    assert os.environ["TOOL_CALLING_PROMPT_PADDING_OBFUSCATE"] == "false"


def test_safe_defaults_do_not_override_explicit_tool_settings(monkeypatch):
    monkeypatch.setenv("TOOL_CALLING_CLIENT_WORKSPACE_REPAIR", "false")
    monkeypatch.setenv("TOOL_CALLING_PROMPT_PADDING_ENABLED", "true")

    ensure_safe_defaults()

    assert os.environ["TOOL_CALLING_CLIENT_WORKSPACE_REPAIR"] == "false"
    assert os.environ["TOOL_CALLING_PROMPT_PADDING_ENABLED"] == "true"


def test_direct_runtime_cors_defaults_are_safe(monkeypatch):
    config_path = Path("app/core/config_parts/env_config.py").resolve()
    spec = importlib.util.spec_from_file_location("uwapi_hardened_env_config", config_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.delenv("CORS_ENABLED", raising=False)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    assert module.AppConfig.is_cors_enabled() is False
    assert module.AppConfig.get_cors_origins() == ["http://127.0.0.1:8199"]


def test_loopback_is_allowed_without_auth():
    validate_runtime_security(
        {
            "APP_HOST": "127.0.0.1",
            "AUTH_ENABLED": "false",
            "CORS_ENABLED": "false",
            "CMD_ALLOW_UNSAFE_PYTHON_COMMANDS": "false",
            "AUTO_UPDATE_ENABLED": "false",
        }
    )


def test_unsafe_python_is_rejected_even_locally():
    with pytest.raises(RuntimeError, match="CMD_ALLOW_UNSAFE_PYTHON_COMMANDS"):
        validate_runtime_security(
            {
                "APP_HOST": "127.0.0.1",
                "CMD_ALLOW_UNSAFE_PYTHON_COMMANDS": "true",
                "AUTO_UPDATE_ENABLED": "false",
                "CORS_ENABLED": "false",
            }
        )


def test_wildcard_cors_is_rejected():
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        validate_runtime_security(
            {
                "APP_HOST": "127.0.0.1",
                "CORS_ENABLED": "true",
                "CORS_ORIGINS": "*",
                "CMD_ALLOW_UNSAFE_PYTHON_COMMANDS": "false",
                "AUTO_UPDATE_ENABLED": "false",
            }
        )


def test_remote_without_opt_in_is_rejected():
    with pytest.raises(RuntimeError, match="UWAPI_ALLOW_REMOTE"):
        validate_runtime_security(
            {
                "APP_HOST": "0.0.0.0",
                "AUTH_ENABLED": "false",
                "CORS_ENABLED": "false",
                "CMD_ALLOW_UNSAFE_PYTHON_COMMANDS": "false",
                "AUTO_UPDATE_ENABLED": "false",
            }
        )


def test_remote_hardened_configuration_is_allowed():
    validate_runtime_security(
        {
            "APP_HOST": "0.0.0.0",
            "UWAPI_ALLOW_REMOTE": "true",
            "AUTH_ENABLED": "true",
            "AUTH_TOKEN": "a" * 40,
            "DASHBOARD_AUTH_ENABLED": "true",
            "DASHBOARD_AUTH_TOKEN": "b" * 40,
            "APP_DEBUG": "false",
            "CORS_ENABLED": "false",
            "CMD_ALLOW_UNSAFE_PYTHON_COMMANDS": "false",
            "AUTO_UPDATE_ENABLED": "false",
        }
    )


def test_auto_update_needs_second_opt_in():
    with pytest.raises(RuntimeError, match="UWAPI_ALLOW_UPSTREAM_AUTO_UPDATE"):
        validate_runtime_security(
            {
                "APP_HOST": "127.0.0.1",
                "AUTO_UPDATE_ENABLED": "true",
                "UWAPI_ALLOW_UPSTREAM_AUTO_UPDATE": "false",
                "CMD_ALLOW_UNSAFE_PYTHON_COMMANDS": "false",
                "CORS_ENABLED": "false",
            }
        )


def test_standalone_start_enforces_loopback_launcher_boundary():
    import start

    assert callable(start._ensure_venv)
    assert start._loopback_host("127.0.0.1") is True
    assert start._loopback_host("localhost") is True
    assert start._loopback_host("::1") is True
    assert start._loopback_host("0.0.0.0") is False
    assert start._loopback_host("192.168.1.8") is False
    assert not hasattr(start, "_build_service_env")
    assert not hasattr(start, "_normalize_python_proxy_url")



def test_public_repo_safety_rejects_raw_conversation_urls():
    samples = [
        "https://chatgpt.com" + "/c/" + "6aaf937d-8174-83ec-b696-a4376db7d1b0",
        "https://arena.ai" + "/c/" + "01a0046f-4413-7684-9fdd-079995af4852",
        "https://grok.com" + "/c/" + "79789b04-1484-4b65-b766-782b020ae0c0",
    ]

    for sample in samples:
        assert any(
            pattern.search(sample)
            for _, pattern in PRIVATE_RUNTIME_TEXT_PATTERNS
        )


def test_public_repo_safety_allows_generic_service_urls():
    samples = [
        "https://chatgpt.com/",
        "https://arena.ai/image/direct",
        "https://grok.com/",
    ]

    for sample in samples:
        assert not any(
            pattern.search(sample)
            for _, pattern in PRIVATE_RUNTIME_TEXT_PATTERNS
        )


def test_tracked_browser_config_has_no_machine_specific_conversation_state():
    import json

    config = json.loads(
        Path("config/browser_config.json").read_text(encoding="utf-8")
    )
    tab_pool = config["tab_pool"]

    assert tab_pool["excluded_urls"] == []
    assert tab_pool["route_groups"] == []
    assert tab_pool["auto_remember_url_presets"] is False



def test_browser_config_private_identifier_pattern_rejects_uuid_like_state():
    sample = "01a0046f-4413-7684-9fdd-079995af4852"
    assert any(
        pattern.search(sample)
        for _, pattern in BROWSER_CONFIG_PRIVATE_PATTERNS
    )
