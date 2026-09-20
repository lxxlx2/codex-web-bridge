from __future__ import annotations

from pathlib import Path

import pytest

from tools import standalone_tagged_source_smoke as smoke


def _write(root: Path, relative: str, text: str = "ok\n") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _release_tree(root: Path) -> None:
    for relative in smoke.REQUIRED_FILES:
        _write(root, relative)
    _write(root, "VERSION", smoke.RC_VERSION + "\n")


def test_require_files_and_version(tmp_path: Path):
    _release_tree(tmp_path)
    smoke.require_files(tmp_path)
    smoke.require_version(tmp_path, smoke.RC_VERSION)

    (tmp_path / "README.md").unlink()
    with pytest.raises(smoke.SmokeFailure, match="missing_files=README.md"):
        smoke.require_files(tmp_path)


def test_require_tag_accepts_expected_tag(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        smoke,
        "_run",
        lambda root, *args: (
            "v0.1.0-rc.1\nother\n"
            if args[:3] == ("git", "tag", "--points-at")
            else ""
        ),
    )
    smoke.require_tag(tmp_path, smoke.RC_TAG)

    with pytest.raises(smoke.SmokeFailure, match="tag_not_at_head"):
        smoke.require_tag(tmp_path, "v9.9.9")


def test_run_passes_with_clean_tagged_fixture(tmp_path: Path, monkeypatch, capsys):
    _release_tree(tmp_path)

    monkeypatch.setattr(smoke, "require_clean", lambda root: None)
    monkeypatch.setattr(smoke, "require_tag", lambda root, expected_tag: None)
    monkeypatch.setattr(smoke, "run_project_checks", lambda root: None)
    monkeypatch.setattr(smoke, "git_head", lambda root: "abc123")

    assert (
        smoke.run(
            root=tmp_path,
            expected_version=smoke.RC_VERSION,
            expected_tag=smoke.RC_TAG,
            check_tag=True,
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "TAGGED_SOURCE_WORKTREE=PASS" in output
    assert "TAGGED_SOURCE_FILES=PASS" in output
    assert "TAGGED_SOURCE_VERSION=PASS" in output
    assert "TAGGED_SOURCE_TAG=PASS" in output
    assert "TAGGED_SOURCE_PUBLIC_SAFETY=PASS" in output
    assert "TAGGED_SOURCE_DEPENDENCY_AUDIT=PASS" in output
    assert "candidate_commit=abc123" in output
    assert "TAGGED_SOURCE_SMOKE=PASS" in output
