import json
import tomllib
from pathlib import Path

from tools import codex_provider_switch as provider_switch

from tools.codex_provider_switch import (
    official_text,
    switch_to_official,
    top_level_status,
    uwa_text,
    write_official,
    write_uwa,
)


def test_official_text_removes_only_top_level_provider_model_pins():
    source = '''model_provider = "uwa"\nmodel = "gpt-5.6-sol"\nmodel_reasoning_effort = "high"\napproval_policy = "on-request"\n\n[model_providers.uwa]\nname = "UWA"\nbase_url = "http://127.0.0.1:8199/v1"\n\n[profiles.keep]\nmodel = "profile-model"\n'''

    updated = official_text(source)

    assert 'model_provider = "uwa"' not in updated
    assert 'model = "gpt-5.6-sol"' not in updated
    assert 'model_reasoning_effort = "high"' not in updated
    assert 'approval_policy = "on-request"' in updated
    assert '[model_providers.uwa]' in updated
    assert 'base_url = "http://127.0.0.1:8199/v1"' in updated
    assert '[profiles.keep]' in updated
    assert 'model = "profile-model"' in updated


def test_uwa_text_sets_exact_bridge_contract_and_preserves_unrelated_config():
    source = '''approval_policy = "never"\nsandbox_mode = "read-only"\nmodel_context_window = 12345\nmodel_auto_compact_token_limit = 10000\nmodel_auto_compact_token_limit_scope = "total"\nmodel_catalog_json = "/tmp/models.json"\nnotify = ["keep-me"]\nservice_tier = "default"\n\n[desktop]\nfollowUpQueueMode = "queue"\n\n[model_providers.other]\nname = "Other"\nbase_url = "http://127.0.0.1:4446/v1"\n\n[model_providers.uwa]\nname = "OLD"\nbase_url = "http://127.0.0.1:9999/v1"\nrequest_max_retries = 7\n\n[plugins."browser@example"]\nenabled = true\n'''

    updated = uwa_text(source)
    parsed = tomllib.loads(updated)

    assert parsed["model"] == "chatgpt"
    assert parsed["model_provider"] == "uwa"
    assert parsed["model_reasoning_effort"] == "high"
    assert parsed["approval_policy"] == "on-request"
    assert parsed["sandbox_mode"] == "workspace-write"
    assert parsed["model_auto_compact_token_limit_scope"] == "body_after_prefix"
    assert "model_context_window" not in parsed
    assert "model_auto_compact_token_limit" not in parsed
    assert "model_catalog_json" not in parsed
    assert parsed["notify"] == ["keep-me"]
    assert parsed["service_tier"] == "default"
    assert parsed["desktop"]["followUpQueueMode"] == "queue"
    assert parsed["model_providers"]["other"]["name"] == "Other"
    assert parsed["model_providers"]["uwa"] == {
        "name": "Universal Web API",
        "base_url": "http://127.0.0.1:8199/v1",
        "wire_api": "responses",
        "requires_openai_auth": False,
        "supports_websockets": False,
        "request_max_retries": 0,
        "stream_max_retries": 0,
        "stream_idle_timeout_ms": 300000,
    }
    assert parsed["plugins"]["browser@example"]["enabled"] is True
    assert "9999" not in updated


def test_write_official_backs_up_before_modifying(tmp_path: Path):
    path = tmp_path / "config.toml"
    source = 'model_provider = "uwa"\nmodel = "gpt-5.6-sol"\n\n[model_providers.uwa]\nname = "UWA"\n'
    path.write_text(source, encoding="utf-8")

    backup, changed = write_official(path)

    assert changed is True
    assert backup is not None
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == source
    assert top_level_status(path.read_text(encoding="utf-8")) == {}
    assert '[model_providers.uwa]' in path.read_text(encoding="utf-8")


def test_write_official_is_idempotent_when_no_top_level_pins(tmp_path: Path):
    path = tmp_path / "config.toml"
    source = 'approval_policy = "on-request"\n\n[model_providers.uwa]\nname = "UWA"\n'
    path.write_text(source, encoding="utf-8")

    backup, changed = write_official(path)

    assert changed is False
    assert backup is None
    assert path.read_text(encoding="utf-8") == source


def test_write_uwa_records_restore_state_without_copying_unrelated_config(tmp_path: Path):
    path = tmp_path / "config.toml"
    state = tmp_path / "provider-state.json"
    source = '''approval_policy = "never"\nsandbox_mode = "read-only"\nmodel_context_window = 98765\nmodel_auto_compact_token_limit = 87654\nmodel_auto_compact_token_limit_scope = "total"\nmodel_catalog_json = "/private/catalog.json"\nnotify = ["keep"]\n\n[plugins.keep]\nenabled = true\n'''
    path.write_text(source, encoding="utf-8")

    backup, changed, state_written = write_uwa(path, state_path=state)

    assert changed is True
    assert state_written is True
    assert backup is not None
    assert backup.read_text(encoding="utf-8") == source
    assert state.stat().st_mode & 0o077 == 0

    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["root"]["approval_policy"] == {"present": True, "rhs": '"never"'}
    assert saved["root"]["sandbox_mode"] == {"present": True, "rhs": '"read-only"'}
    assert saved["root"]["model_context_window"] == {"present": True, "rhs": "98765"}
    assert saved["root"]["model_auto_compact_token_limit"] == {
        "present": True,
        "rhs": "87654",
    }
    assert saved["root"]["model_auto_compact_token_limit_scope"] == {
        "present": True,
        "rhs": '"total"',
    }
    assert saved["root"]["model_catalog_json"] == {
        "present": True,
        "rhs": '"/private/catalog.json"',
    }

    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["notify"] == ["keep"]
    assert parsed["plugins"]["keep"]["enabled"] is True
    assert parsed["model_provider"] == "uwa"
    assert parsed["model_auto_compact_token_limit_scope"] == "body_after_prefix"


def test_write_uwa_upgrades_existing_legacy_state_before_scope_override(tmp_path: Path):
    path = tmp_path / "config.toml"
    state = tmp_path / "provider-state.json"
    path.write_text(
        'model = "chatgpt"\n'
        'model_provider = "uwa"\n'
        'model_reasoning_effort = "high"\n'
        'model_auto_compact_token_limit_scope = "total"\n\n'
        '[model_providers.uwa]\n'
        'name = "Universal Web API"\n',
        encoding="utf-8",
    )
    state.write_text(
        json.dumps(
            {
                "version": 1,
                "root": {
                    "approval_policy": {"present": False, "rhs": None},
                    "sandbox_mode": {"present": False, "rhs": None},
                    "model_context_window": {"present": False, "rhs": None},
                    "model_auto_compact_token_limit": {"present": False, "rhs": None},
                    "model_catalog_json": {"present": False, "rhs": None},
                },
            }
        ),
        encoding="utf-8",
    )

    _, changed, state_written = write_uwa(path, state_path=state)

    assert changed is True
    assert state_written is True
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["root"]["model_auto_compact_token_limit_scope"] == {
        "present": True,
        "rhs": '"total"',
    }
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["model_auto_compact_token_limit_scope"] == "body_after_prefix"


def test_switch_to_official_restores_pre_uwa_policy_context_state(tmp_path: Path):
    path = tmp_path / "config.toml"
    state = tmp_path / "provider-state.json"
    original = '''approval_policy = "never"\nsandbox_mode = "read-only"\nmodel_context_window = 98765\nmodel_auto_compact_token_limit = 87654\nmodel_auto_compact_token_limit_scope = "total"\nmodel_catalog_json = "/private/catalog.json"\nnotify = ["keep"]\n'''
    path.write_text(original, encoding="utf-8")
    write_uwa(path, state_path=state)

    events: list[str] = []

    def restore_fn(config_path: Path) -> None:
        assert config_path == path
        events.append("restore")

    _, changed, stopped_apps, stopped_pids, reopened = switch_to_official(
        path,
        automate_desktop=False,
        automate_uwa_stop=False,
        state_path=state,
        restore_fn=restore_fn,
    )

    assert changed is True
    assert events == ["restore"]
    assert stopped_apps == []
    assert stopped_pids == []
    assert reopened == "SKIPPED"
    assert not state.exists()

    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert "model" not in parsed
    assert "model_provider" not in parsed
    assert "model_reasoning_effort" not in parsed
    assert parsed["approval_policy"] == "never"
    assert parsed["sandbox_mode"] == "read-only"
    assert parsed["model_context_window"] == 98765
    assert parsed["model_auto_compact_token_limit"] == 87654
    assert parsed["model_auto_compact_token_limit_scope"] == "total"
    assert parsed["model_catalog_json"] == "/private/catalog.json"
    assert parsed["notify"] == ["keep"]
    assert parsed["model_providers"]["uwa"]["base_url"] == "http://127.0.0.1:8199/v1"


def test_switch_to_official_removes_uwa_scope_when_original_was_default(tmp_path: Path):
    path = tmp_path / "config.toml"
    state = tmp_path / "provider-state.json"
    path.write_text('notify = ["keep"]\n', encoding="utf-8")
    write_uwa(path, state_path=state)

    def restore_fn(config_path: Path) -> None:
        assert config_path == path

    switch_to_official(
        path,
        automate_desktop=False,
        automate_uwa_stop=False,
        state_path=state,
        restore_fn=restore_fn,
    )

    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert "model_auto_compact_token_limit_scope" not in parsed
    assert parsed["notify"] == ["keep"]


def test_official_with_legacy_state_does_not_delete_unmanaged_scope():
    source = 'model_provider = "uwa"\nmodel_auto_compact_token_limit_scope = "total"\n'
    legacy_state = {
        "version": 1,
        "root": {
            "approval_policy": {"present": False, "rhs": None},
            "sandbox_mode": {"present": False, "rhs": None},
            "model_context_window": {"present": False, "rhs": None},
            "model_auto_compact_token_limit": {"present": False, "rhs": None},
            "model_catalog_json": {"present": False, "rhs": None},
        },
    }

    updated = official_text(source, restore_state=legacy_state)
    parsed = tomllib.loads(updated)

    assert "model_provider" not in parsed
    assert parsed["model_auto_compact_token_limit_scope"] == "total"


def test_switch_to_official_automates_quit_stop_restore_cleanup_and_reopen(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        'model_provider = "uwa"\n'
        'model = "chatgpt"\n'
        'model_reasoning_effort = "high"\n'
        'approval_policy = "on-request"\n\n'
        '[model_providers.uwa]\n'
        'name = "UWA"\n',
        encoding="utf-8",
    )

    events: list[str] = []

    def quit_fn() -> list[str]:
        events.append("quit_desktop")
        return ["ChatGPT"]

    def stop_fn() -> list[int]:
        events.append("stop_uwa")
        return [12345]

    def restore_fn(config_path: Path) -> None:
        assert config_path == path
        events.append("restore_memories")
        text = config_path.read_text(encoding="utf-8")
        config_path.write_text(text + '\n[memories]\nuse_memories = true\n', encoding="utf-8")

    def open_fn() -> str:
        events.append("open_desktop")
        return "ChatGPT"

    backup, changed, stopped_apps, stopped_pids, reopened = switch_to_official(
        path,
        quit_fn=quit_fn,
        stop_fn=stop_fn,
        restore_fn=restore_fn,
        open_fn=open_fn,
    )

    assert events == [
        "quit_desktop",
        "stop_uwa",
        "restore_memories",
        "open_desktop",
    ]
    assert changed is True
    assert backup is not None
    assert stopped_apps == ["ChatGPT"]
    assert stopped_pids == [12345]
    assert reopened == "ChatGPT"

    updated = path.read_text(encoding="utf-8")
    assert top_level_status(updated) == {}
    assert 'approval_policy = "on-request"' in updated
    assert '[model_providers.uwa]' in updated
    assert '[memories]' in updated
    assert 'use_memories = true' in updated


def test_switch_to_official_can_skip_desktop_and_uwa_automation(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('model_provider = "uwa"\n', encoding="utf-8")

    calls: list[str] = []

    def forbidden_quit() -> list[str]:
        calls.append("quit")
        raise AssertionError("desktop quit should be skipped")

    def forbidden_stop() -> list[int]:
        calls.append("stop")
        raise AssertionError("UWA stop should be skipped")

    def restore_fn(config_path: Path) -> None:
        calls.append("restore")

    def forbidden_open() -> str:
        calls.append("open")
        raise AssertionError("desktop open should be skipped")

    _, changed, stopped_apps, stopped_pids, reopened = switch_to_official(
        path,
        automate_desktop=False,
        automate_uwa_stop=False,
        quit_fn=forbidden_quit,
        stop_fn=forbidden_stop,
        restore_fn=restore_fn,
        open_fn=forbidden_open,
    )

    assert changed is True
    assert calls == ["restore"]
    assert stopped_apps == []
    assert stopped_pids == []
    assert reopened == "SKIPPED"
    assert top_level_status(path.read_text(encoding="utf-8")) == {}

def test_stop_uwa_listener_delegates_to_hardened_lifecycle(monkeypatch, tmp_path: Path):
    calls = {}

    def fake_stop_uwa(**kwargs):
        calls.update(kwargs)
        return (9101, 9102)

    monkeypatch.setattr(provider_switch, "stop_uwa_lifecycle", fake_stop_uwa)

    stopped = provider_switch.stop_uwa_listener(
        repo_root=tmp_path,
        timeout_sec=3.5,
        sleeper=lambda _: None,
    )

    assert stopped == [9101, 9102]
    assert calls["repo_root"] == tmp_path
    assert calls["port"] == provider_switch.UWA_PORT
    assert calls["timeout_sec"] == 3.5


def test_switch_to_official_default_stop_path_uses_hardened_wrapper(monkeypatch, tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('model_provider = "uwa"\n', encoding="utf-8")
    events = []

    def fake_stop():
        events.append("stop")
        return [9201]

    monkeypatch.setattr(provider_switch, "stop_uwa_listener", fake_stop)

    _, changed, stopped_apps, stopped_pids, reopened = provider_switch.switch_to_official(
        path,
        automate_desktop=False,
        restore_fn=lambda _: None,
    )

    assert changed is True
    assert events == ["stop"]
    assert stopped_apps == []
    assert stopped_pids == [9201]
    assert reopened == "SKIPPED"
