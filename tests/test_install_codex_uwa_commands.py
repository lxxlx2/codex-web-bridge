from pathlib import Path

from tools.install_codex_uwa_commands import START_WRAPPER, STOP_WRAPPER, install


def test_install_writes_executable_thin_wrappers(tmp_path: Path):
    start, stop = install(tmp_path)

    assert start == tmp_path / "codex-uwa"
    assert stop == tmp_path / "codex-uwa-stop"
    assert start.read_text(encoding="utf-8") == START_WRAPPER
    assert stop.read_text(encoding="utf-8") == STOP_WRAPPER
    assert start.stat().st_mode & 0o111
    assert stop.stat().st_mode & 0o111


def test_stop_wrapper_delegates_lifecycle_to_repository():
    assert 'codex_uwa_lifecycle.py" stop' in STOP_WRAPPER
    assert "lsof" not in STOP_WRAPPER
    assert "kill " not in STOP_WRAPPER


def test_start_wrapper_uses_verified_restart_not_health_reuse():
    assert 'codex_uwa_lifecycle.py" restart' in START_WRAPPER
    assert 'codex_uwa_lifecycle.py" start' not in START_WRAPPER
    assert "health_ok" not in START_WRAPPER


def test_start_wrapper_disables_memories_automatically():
    assert 'codex_uwa_memory_guard.py" disable' in START_WRAPPER


def test_start_wrapper_uses_repository_provider_switch_without_private_helper():
    assert 'codex_provider_switch.py" uwa' in START_WRAPPER
    assert "config_switch.py" not in START_WRAPPER
