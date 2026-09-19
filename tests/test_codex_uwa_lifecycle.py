from pathlib import Path

import pytest

from tools import codex_uwa_lifecycle as lifecycle


def test_stop_uwa_requires_owned_listener_and_proves_port_empty(monkeypatch, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    state = tmp_path / "state"
    state.mkdir()

    calls = iter(([101], [101], []))
    monkeypatch.setattr(lifecycle, "listener_pids", lambda *args, **kwargs: list(next(calls)))
    monkeypatch.setattr(lifecycle, "process_cwd", lambda pid, **kwargs: root)
    monkeypatch.setattr(lifecycle, "_owned_launcher_candidates", lambda *args, **kwargs: [])

    signals: list[tuple[int, int]] = []

    stopped = lifecycle.stop_uwa(
        repo_root=root,
        state_dir=state,
        timeout_sec=1,
        sleeper=lambda _: None,
        killer=lambda pid, sig: signals.append((pid, sig)),
    )

    assert stopped == (101,)
    assert signals == [(101, lifecycle.signal.SIGTERM)]


def test_stop_uwa_escalates_to_kill_and_rechecks(monkeypatch, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    state = tmp_path / "state"
    state.mkdir()

    listener_calls = iter(([202], [202]))
    monkeypatch.setattr(lifecycle, "listener_pids", lambda *args, **kwargs: list(next(listener_calls)))
    monkeypatch.setattr(lifecycle, "process_cwd", lambda pid, **kwargs: root)
    monkeypatch.setattr(lifecycle, "_owned_launcher_candidates", lambda *args, **kwargs: [201])

    waits = iter((False, True))
    monkeypatch.setattr(lifecycle, "_wait_for_empty_port", lambda **kwargs: next(waits))

    signals: list[tuple[int, int]] = []

    stopped = lifecycle.stop_uwa(
        repo_root=root,
        state_dir=state,
        timeout_sec=1,
        sleeper=lambda _: None,
        killer=lambda pid, sig: signals.append((pid, sig)),
    )

    assert stopped == (202,)
    assert (201, lifecycle.signal.SIGTERM) in signals
    assert (202, lifecycle.signal.SIGTERM) in signals
    assert (202, lifecycle.signal.SIGKILL) in signals
    assert (201, lifecycle.signal.SIGKILL) in signals


def test_stop_uwa_fails_closed_for_foreign_listener(monkeypatch, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    foreign = tmp_path / "other"
    foreign.mkdir()

    monkeypatch.setattr(lifecycle, "listener_pids", lambda *args, **kwargs: [303])
    monkeypatch.setattr(lifecycle, "process_cwd", lambda pid, **kwargs: foreign)

    with pytest.raises(RuntimeError, match="refusing to touch listener 303"):
        lifecycle.stop_uwa(repo_root=root, state_dir=tmp_path / "state")


def test_restart_uwa_always_calls_stop_then_start(monkeypatch, tmp_path: Path):
    events: list[str] = []

    def fake_stop(**kwargs):
        events.append("stop")
        return (401,)

    def fake_start(**kwargs):
        events.append("start")
        return lifecycle.StartResult(launcher_pid=500, listener_pids=(501,))

    monkeypatch.setattr(lifecycle, "stop_uwa", fake_stop)
    monkeypatch.setattr(lifecycle, "start_uwa", fake_start)

    result = lifecycle.restart_uwa(repo_root=tmp_path)

    assert events == ["stop", "start"]
    assert result.old_listener_pids == (401,)
    assert result.start.listener_pids == (501,)


def test_restart_uwa_rejects_listener_pid_reuse(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(lifecycle, "stop_uwa", lambda **kwargs: (601,))
    monkeypatch.setattr(
        lifecycle,
        "start_uwa",
        lambda **kwargs: lifecycle.StartResult(launcher_pid=700, listener_pids=(601,)),
    )

    with pytest.raises(RuntimeError, match="did not prove listener replacement"):
        lifecycle.restart_uwa(repo_root=tmp_path)
