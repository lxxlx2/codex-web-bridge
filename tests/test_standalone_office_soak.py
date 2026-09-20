"""Tests for the release-blocking office-work soak gate.

These tests do not touch ChatGPT Web. They validate orchestration semantics:
fail-closed behavior, no retry after a failed live turn, scenario ordering,
candidate-bound evidence, and external surface classification.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import standalone_office_soak as soak


def _obs(
    message: str,
    *,
    thread_id: str = "thread-1",
    tools: int = 1,
):
    return SimpleNamespace(
        returncode=0,
        final_message=message,
        tool_effect_count=tools,
        thread_ids=[thread_id],
    )


def _install_common_mocks(tmp_path: Path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir()

    monkeypatch.setattr(soak.core, "_private_dir", lambda root: private)
    monkeypatch.setattr(soak.core, "_preflight_repo", lambda: None)
    monkeypatch.setattr(soak, "_candidate_commit", lambda: "abc123")
    monkeypatch.setattr(soak.core, "_configure_uwa_route", lambda: None)
    monkeypatch.setattr(soak.core, "_start_standalone_listener", lambda: "STARTED")
    monkeypatch.setattr(soak.core, "_health_ready", lambda **kwargs: {})
    monkeypatch.setattr(soak.s3, "_passive_surface_recheck", lambda private: {})
    monkeypatch.setattr(soak.route_audit, "write_marker", lambda: 123.0)
    monkeypatch.setattr(soak.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(soak, "_pace", lambda last: None)
    monkeypatch.setattr(soak.core, "_wait_request_cleanup", lambda: None)
    monkeypatch.setattr(soak.core, "_route_gate", lambda marker: None)

    class GitResult:
        returncode = 0
        stdout = ""

    monkeypatch.setattr(soak.core, "_git", lambda *args, **kwargs: GitResult())
    return private


def test_happy_path_runs_context_then_all_office_scenarios(
    tmp_path: Path,
    monkeypatch,
):
    private = _install_common_mocks(tmp_path, monkeypatch)
    prepared = []
    checked = []
    monkeypatch.setattr(soak, "_prepare", lambda root, scenario: prepared.append(scenario))
    monkeypatch.setattr(soak, "_check", lambda root, scenario: checked.append(scenario))

    replies = iter(
        [
            _obs("CONTEXT_READY", tools=0),
            _obs("CONTEXT_PASS"),
            _obs("multi-file complete"),
            _obs("failure recovery complete"),
            _obs("git diff complete"),
            _obs("interactive complete"),
        ]
    )
    monkeypatch.setattr(soak, "_run_turn", lambda **kwargs: next(replies))

    rc = soak.run(
        acceptance_root=tmp_path / "acceptance",
        private_root=tmp_path / "unused",
        turn_timeout_sec=60,
    )

    assert rc == 0
    assert prepared == [
        "context",
        "multi_file",
        "failure_recovery",
        "git_diff",
        "interactive",
    ]
    assert checked == prepared

    result = (private / "result.txt").read_text(encoding="utf-8")
    assert "STANDALONE_OFFICE_SOAK=PASS" in result
    assert "OFFICE_SOAK_TURN_COUNT=6" in result
    assert "candidate_commit=abc123" in result


def test_failed_live_turn_stops_without_replaying_later_scenarios(
    tmp_path: Path,
    monkeypatch,
):
    private = _install_common_mocks(tmp_path, monkeypatch)
    prepared = []
    monkeypatch.setattr(soak, "_prepare", lambda root, scenario: prepared.append(scenario))
    monkeypatch.setattr(soak, "_check", lambda root, scenario: None)
    monkeypatch.setattr(
        soak,
        "_classify_surface_after_turn_failure",
        lambda private_dir, failure: failure,
    )

    calls = 0

    def run_turn(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _obs("CONTEXT_READY", tools=0)
        if calls == 2:
            return _obs("CONTEXT_PASS")
        raise soak.GateFailure("office_soak_codex_turn", "rc=1")

    monkeypatch.setattr(soak, "_run_turn", run_turn)

    rc = soak.run(
        acceptance_root=tmp_path / "acceptance",
        private_root=tmp_path / "unused",
        turn_timeout_sec=60,
    )

    assert rc == 1
    assert calls == 3
    assert prepared == ["context", "multi_file"]
    result = (private / "result.txt").read_text(encoding="utf-8")
    assert "STANDALONE_OFFICE_SOAK=FAIL" in result
    assert "FAILURE_CLASS=office_soak_codex_turn" in result


def test_effect_verification_failure_stops_before_next_scenario(
    tmp_path: Path,
    monkeypatch,
):
    _install_common_mocks(tmp_path, monkeypatch)
    prepared = []
    monkeypatch.setattr(soak, "_prepare", lambda root, scenario: prepared.append(scenario))

    def check(root, scenario):
        if scenario == "multi_file":
            raise soak.GateFailure(
                "office_soak_effect_verification",
                "scenario=multi_file",
            )

    monkeypatch.setattr(soak, "_check", check)

    replies = iter(
        [
            _obs("CONTEXT_READY", tools=0),
            _obs("CONTEXT_PASS"),
            _obs("multi-file complete"),
        ]
    )
    monkeypatch.setattr(soak, "_run_turn", lambda **kwargs: next(replies))

    rc = soak.run(
        acceptance_root=tmp_path / "acceptance",
        private_root=tmp_path / "unused",
        turn_timeout_sec=60,
    )

    assert rc == 1
    assert prepared == ["context", "multi_file"]


def test_context_resume_must_keep_same_thread(
    tmp_path: Path,
    monkeypatch,
):
    _install_common_mocks(tmp_path, monkeypatch)
    monkeypatch.setattr(soak, "_prepare", lambda root, scenario: None)
    monkeypatch.setattr(soak, "_check", lambda root, scenario: None)

    replies = iter(
        [
            _obs("CONTEXT_READY", thread_id="thread-a", tools=0),
            _obs("CONTEXT_PASS", thread_id="thread-b"),
        ]
    )
    monkeypatch.setattr(soak, "_run_turn", lambda **kwargs: next(replies))

    rc = soak.run(
        acceptance_root=tmp_path / "acceptance",
        private_root=tmp_path / "unused",
        turn_timeout_sec=60,
    )

    assert rc == 1


def test_run_turn_wraps_core_transport_failure_for_surface_classification(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr(
        soak.core,
        "_run_codex_turn",
        lambda **kwargs: (_ for _ in ()).throw(
            soak.core.GateFailure("subprocess_timeout", "timeout=60s")
        ),
    )

    with pytest.raises(
        soak.GateFailure,
        match="subprocess_timeout:timeout=60s",
    ) as exc:
        soak._run_turn(
            codex="/usr/bin/codex",
            root=tmp_path,
            prompt="synthetic",
            trace_path=tmp_path / "trace.jsonl",
            thread_id=None,
            timeout_sec=60,
            require_tool_effect=False,
        )

    assert exc.value.gate == "office_soak_codex_turn"


def test_surface_rate_limit_reclassifies_live_turn_failure(
    tmp_path: Path,
    monkeypatch,
):
    def blocked(_private):
        raise soak.core.GateFailure(
            "chatgpt_web_rate_limited",
            "rate_limited",
        )

    monkeypatch.setattr(soak.s3, "_passive_surface_recheck", blocked)
    original = soak.GateFailure("office_soak_codex_turn", "rc=1")

    classified = soak._classify_surface_after_turn_failure(
        tmp_path,
        original,
    )

    assert classified.gate == "chatgpt_web_rate_limited"
    assert classified.detail == "rate_limited"


def test_turn_gap_is_bounded(monkeypatch):
    monkeypatch.setenv("UWA_OFFICE_SOAK_TURN_GAP_SEC", "999")
    assert soak._turn_gap_seconds() == 120

    monkeypatch.setenv("UWA_OFFICE_SOAK_TURN_GAP_SEC", "-5")
    assert soak._turn_gap_seconds() == 0
