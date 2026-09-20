from __future__ import annotations

from pathlib import Path

import pytest

from tools import standalone_s4_release_gate as gate


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _release_tree(root: Path) -> None:
    for relative in gate.REQUIRED_DOCS:
        _write(root, relative, "release control\n")

    _write(root, "VERSION", gate.RC_VERSION + "\n")
    _write(root, "CHANGELOG.md", f"# Changelog\n\n## {gate.RC_VERSION}\n")
    _write(root, "docs/RELEASE_PROCESS.md", f"release {gate.RC_TAG}\n")
    _write(
        root,
        "docs/RELEASE_REQUIREMENTS.md",
        "REQUIREMENTS_APPROVED=YES\n",
    )
    _write(
        root,
        "docs/RELEASE_TECHNICAL_DESIGN.md",
        "TECH_DESIGN_APPROVED=YES\n",
    )
    _write(
        root,
        "docs/RELEASE_TEST_PLAN.md",
        "TEST_PLAN_APPROVED=YES\n",
    )
    _write(
        root,
        "SECURITY.md",
        "127.0.0.1\nCORS off\nunsafe Python off\nconversation URL private\n",
    )
    _write(
        root,
        "config/browser_config.json",
        (
            '{"tab_pool":{'
            '"excluded_urls":[],'
            '"route_groups":[],'
            '"auto_remember_url_presets":false'
            '}}\n'
        ),
    )
    _write(
        root,
        "NOTICE.md",
        "\n".join(
            [
                "lumingya/universal-web-api",
                "lxxlx2/universal-web-api",
                "leeguooooo/chatgpt-use",
                "kev489/gpt-tool-use",
            ]
        )
        + "\n",
    )


def _smoke_text(candidate: str = "abc123") -> str:
    return (
        "INSTALL_SMOKE=PASS\n"
        "OFFICIAL_ROLLBACK=PASS\n"
        "BASIC_CODEX_REQUEST=PASS\n"
        "AUTH=UNCHANGED\n"
        "WRAPPER_ROOT=PASS\n"
        "LISTENER_OWNERSHIP=PASS\n"
        f"candidate_commit={candidate}\n"
    )


def _desktop_text(candidate: str = "abc123") -> str:
    return (
        "STANDALONE_DESKTOP_E2E=PASS\n"
        "DESKTOP_CONTEXT=PASS\n"
        "DESKTOP_LOCAL_TOOLS=PASS\n"
        "DESKTOP_ROUTE_UWA_CHATGPT_HIGH=PASS\n"
        "DESKTOP_REQUEST_MANAGER_CLEAN=PASS\n"
        f"candidate_commit={candidate}\n"
    )


def test_docs_gate_rejects_missing_file(tmp_path: Path):
    with pytest.raises(gate.GateFailure, match="missing=README.md"):
        gate.check_docs(tmp_path)


def test_docs_gate_rejects_stale_status(tmp_path: Path):
    _release_tree(tmp_path)
    _write(tmp_path, "README.md", "S3 = OPEN\n")

    with pytest.raises(gate.GateFailure, match="stale_text"):
        gate.check_docs(tmp_path)


def test_docs_gate_rejects_release_quick_start_dev_branch(tmp_path: Path):
    _release_tree(tmp_path)
    _write(
        tmp_path,
        "README.md",
        "git clone repo\ngit switch standalone-dev\n",
    )

    with pytest.raises(
        gate.GateFailure,
        match="release_quick_start_uses_dev_branch",
    ):
        gate.check_docs(tmp_path)


def test_security_gate_rejects_tracked_browser_conversation_state(tmp_path: Path):
    _release_tree(tmp_path)
    gate.check_security(tmp_path)

    _write(
        tmp_path,
        "config/browser_config.json",
        (
            '{"tab_pool":{'
            '"excluded_urls":["https://arena.ai' + '/c/' + '01a0046f-4413-7684-9fdd-079995af4852"],'
            '"route_groups":[],'
            '"auto_remember_url_presets":false'
            '}}\n'
        ),
    )

    with pytest.raises(
        gate.GateFailure,
        match="tracked_excluded_urls_not_empty",
    ):
        gate.check_security(tmp_path)


def test_version_gate_requires_rc_version_and_changelog(tmp_path: Path):
    _release_tree(tmp_path)
    gate.check_version(tmp_path)

    _write(tmp_path, "VERSION", "0.1.0-dev\n")
    with pytest.raises(gate.GateFailure, match="version=0.1.0-dev"):
        gate.check_version(tmp_path)


def test_provenance_requires_reliability_acknowledgements(tmp_path: Path):
    _release_tree(tmp_path)
    gate.check_provenance(tmp_path)

    _write(tmp_path, "NOTICE.md", "lumingya/universal-web-api\n")
    with pytest.raises(gate.GateFailure, match="missing="):
        gate.check_provenance(tmp_path)


def test_s3_candidate_must_match_head(tmp_path: Path, monkeypatch):
    result = tmp_path / "result.txt"
    result.write_text(
        "STANDALONE_S3=PASS_LIVE_CLOSED\n"
        "candidate_commit=abc123\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "git_head", lambda root: "abc123")
    gate.check_s3_candidate(tmp_path, result)

    monkeypatch.setattr(gate, "git_head", lambda root: "different")
    with pytest.raises(gate.GateFailure, match="candidate_sha_mismatch"):
        gate.check_s3_candidate(tmp_path, result)


def test_desktop_candidate_requires_all_markers_and_same_head(tmp_path: Path, monkeypatch):
    result = tmp_path / "desktop.txt"
    result.write_text(_desktop_text("abc123"), encoding="utf-8")
    monkeypatch.setattr(gate, "git_head", lambda root: "abc123")
    gate.check_desktop_candidate(tmp_path, result)

    result.write_text("STANDALONE_DESKTOP_E2E=PASS\n", encoding="utf-8")
    with pytest.raises(gate.GateFailure, match="desktop_context_not_pass"):
        gate.check_desktop_candidate(tmp_path, result)

    result.write_text(_desktop_text("old"), encoding="utf-8")
    with pytest.raises(gate.GateFailure, match="candidate_sha_mismatch"):
        gate.check_desktop_candidate(tmp_path, result)


def test_install_smoke_requires_all_release_markers_and_candidate(tmp_path: Path):
    result = tmp_path / "install.txt"
    result.write_text(_smoke_text("abc123"), encoding="utf-8")
    gate.check_install_smoke(result, expected_candidate="abc123")

    result.write_text("INSTALL_SMOKE=PASS\n", encoding="utf-8")
    with pytest.raises(gate.GateFailure, match="official_rollback_not_pass"):
        gate.check_install_smoke(result)

    result.write_text(_smoke_text("old"), encoding="utf-8")
    with pytest.raises(gate.GateFailure, match="candidate_sha_mismatch"):
        gate.check_install_smoke(result, expected_candidate="new")


def test_full_release_checks_accept_clean_fixture(tmp_path: Path, monkeypatch):
    _release_tree(tmp_path)
    s3 = tmp_path / "s3.txt"
    s3.write_text(
        "STANDALONE_S3=PASS_LIVE_CLOSED\n"
        "candidate_commit=abc123\n",
        encoding="utf-8",
    )
    desktop = tmp_path / "desktop.txt"
    desktop.write_text(_desktop_text("abc123"), encoding="utf-8")
    smoke = tmp_path / "smoke.txt"
    smoke.write_text(_smoke_text("abc123"), encoding="utf-8")
    monkeypatch.setattr(gate, "require_clean_worktree", lambda root: None)
    monkeypatch.setattr(gate, "git_head", lambda root: "abc123")

    assert (
        gate.run(
            root=tmp_path,
            s3_result=s3,
            desktop_result=desktop,
            install_smoke_result=smoke,
        )
        == 0
    )
