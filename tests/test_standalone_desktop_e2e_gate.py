from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

import pytest

from tools import standalone_desktop_e2e_gate as gate


def _state(path: Path, *, candidate: str = "abc123", root: Path | None = None) -> Path:
    payload = {
        "version": 1,
        "candidate_commit": candidate,
        "acceptance_root": str(root or path.parent / "acceptance"),
        "marker_epoch": 123.0,
        "private_dir": str(path.parent / "private"),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_read_state_rejects_missing_or_invalid(tmp_path: Path):
    with pytest.raises(gate.GateFailure, match="state_missing_or_invalid"):
        gate._read_state(tmp_path / "missing.json")

    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(gate.GateFailure, match="state_invalid"):
        gate._read_state(invalid)


def test_prepare_fails_closed_before_opening_desktop_on_blocked_surface(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr(gate.core, "_private_dir", lambda root: tmp_path / "private")
    monkeypatch.setattr(gate.core, "_preflight_repo", lambda: None)
    monkeypatch.setattr(gate, "_candidate_commit", lambda: "abc123")
    monkeypatch.setattr(gate.core, "_configure_uwa_route", lambda: None)
    monkeypatch.setattr(gate.core, "_start_standalone_listener", lambda: "STARTED")
    monkeypatch.setattr(gate.core, "_health_ready", lambda **kwargs: {})
    monkeypatch.setattr(
        gate.s3,
        "_passive_surface_recheck",
        lambda private: (_ for _ in ()).throw(
            gate.core.GateFailure("chatgpt_web_rate_limited", "rate_limited")
        ),
    )
    opened: list[Path] = []
    monkeypatch.setattr(gate, "_open_desktop", lambda root: opened.append(root))

    rc = gate.prepare(
        acceptance_root=tmp_path / "acceptance",
        state_path=tmp_path / "state.json",
    )

    assert rc == 1
    assert opened == []
    assert not (tmp_path / "state.json").exists()


def test_verify_rejects_candidate_mismatch_before_scenario_checks(
    tmp_path: Path,
    monkeypatch,
):
    state = _state(tmp_path / "state.json", candidate="old")
    monkeypatch.setattr(gate, "_candidate_commit", lambda: "new")
    called: list[str] = []
    monkeypatch.setattr(gate, "_scenario_check", lambda root, scenario: called.append(scenario))

    rc = gate.verify(state_path=state)

    assert rc == 1
    assert called == []


def test_verify_accepts_context_tools_route_and_clean_candidate(
    tmp_path: Path,
    monkeypatch,
):
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    state = _state(tmp_path / "state.json", root=acceptance)

    monkeypatch.setattr(gate, "_candidate_commit", lambda: "abc123")
    monkeypatch.setattr(gate.core, "_preflight_repo", lambda: None)
    monkeypatch.setattr(gate.core, "_health_ready", lambda **kwargs: {})
    monkeypatch.setattr(gate.core, "_wait_request_cleanup", lambda: None)
    monkeypatch.setattr(gate, "_route_gate", lambda marker: None)
    monkeypatch.setattr(gate, "_desktop_running", lambda: True)

    scenarios: list[str] = []
    monkeypatch.setattr(
        gate,
        "_scenario_check",
        lambda root, scenario: scenarios.append(scenario),
    )

    class Result:
        returncode = 0
        stdout = ""

    monkeypatch.setattr(gate.core, "_git", lambda *args, **kwargs: Result())
    monkeypatch.setattr(
        gate.core,
        "_assert_candidate_identity",
        lambda candidate: None,
    )
    written: list[str] = []
    monkeypatch.setattr(gate, "_write_result", lambda candidate: written.append(candidate))

    rc = gate.verify(state_path=state)

    assert rc == 0
    assert scenarios == ["context", "multi_file"]
    assert written == ["abc123"]


def test_route_gate_wraps_core_failure(monkeypatch):
    monkeypatch.setattr(
        gate.core,
        "_route_gate",
        lambda marker: (_ for _ in ()).throw(
            gate.core.GateFailure("route_audit", "expectation_failed")
        ),
    )

    with pytest.raises(gate.GateFailure, match="expectation_failed") as exc:
        gate._route_gate(123.0)

    assert exc.value.gate == "desktop_route"

def test_desktop_running_prefers_native_macos_application_state(monkeypatch):
    monkeypatch.setattr(gate.platform, "system", lambda: "Darwin")
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="true\n")

    monkeypatch.setattr(gate.subprocess, "run", fake_run)

    assert gate._desktop_running() is True
    assert calls == [["osascript", "-e", 'application "Codex" is running']]


def test_desktop_running_uses_process_fallback_when_applescript_fails(monkeypatch):
    monkeypatch.setattr(gate.platform, "system", lambda: "Darwin")
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[0] == "osascript":
            return SimpleNamespace(returncode=1, stdout="")
        return SimpleNamespace(returncode=0, stdout="123\n")

    monkeypatch.setattr(gate.subprocess, "run", fake_run)

    assert gate._desktop_running() is True
    assert calls[1][:2] == ["pgrep", "-f"]

