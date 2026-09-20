#!/usr/bin/env python3
"""Lightweight smoke for a fresh checkout of a release tag."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


RC_VERSION = "0.1.0-rc.1"
RC_TAG = "v0.1.0-rc.1"

REQUIRED_FILES = (
    "VERSION",
    "README.md",
    "README.en.md",
    "README.zh-CN.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "LICENSE",
    "NOTICE.md",
    "SECURITY.md",
    "requirements.txt",
    "requirements-dev.txt",
    "docs/README.md",
    "docs/ARCHITECTURE.md",
    "docs/DEVELOPMENT.md",
    "docs/TESTING.md",
    "docs/TROUBLESHOOTING.md",
    "docs/ROADMAP.md",
    "tools/public_repo_safety_check.py",
    "tools/standalone_dependency_audit.py",
)


class SmokeFailure(RuntimeError):
    pass


def _run(root: Path, *args: str) -> str:
    result = subprocess.run(
        list(args),
        cwd=str(root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        joined = " ".join(args)
        raise SmokeFailure(
            f"command_failed={joined}\n"
            f"{result.stdout[-4000:]}"
        )
    return result.stdout.strip()


def git_head(root: Path) -> str:
    return _run(root, "git", "rev-parse", "HEAD")


def require_clean(root: Path) -> None:
    status = _run(
        root,
        "git",
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    if status:
        raise SmokeFailure("worktree_dirty")


def require_files(root: Path) -> None:
    missing = [
        relative
        for relative in REQUIRED_FILES
        if not (root / relative).is_file()
    ]
    if missing:
        raise SmokeFailure(
            "missing_files=" + ",".join(missing)
        )


def require_version(root: Path, expected_version: str) -> None:
    actual = (root / "VERSION").read_text(
        encoding="utf-8"
    ).strip()
    if actual != expected_version:
        raise SmokeFailure(
            f"version_mismatch={actual or 'EMPTY'}"
        )


def require_tag(
    root: Path,
    expected_tag: str,
) -> None:
    tags = {
        line.strip()
        for line in _run(
            root,
            "git",
            "tag",
            "--points-at",
            "HEAD",
        ).splitlines()
        if line.strip()
    }
    if expected_tag not in tags:
        raise SmokeFailure(
            f"tag_not_at_head={expected_tag}"
        )


def run_project_checks(root: Path) -> None:
    _run(
        root,
        sys.executable,
        "tools/public_repo_safety_check.py",
    )
    _run(
        root,
        sys.executable,
        "tools/standalone_dependency_audit.py",
        "--check",
    )


def run(
    *,
    root: Path,
    expected_version: str,
    expected_tag: str,
    check_tag: bool,
) -> int:
    try:
        require_clean(root)
        print("TAGGED_SOURCE_WORKTREE=PASS", flush=True)
        require_files(root)
        print("TAGGED_SOURCE_FILES=PASS", flush=True)
        require_version(root, expected_version)
        print("TAGGED_SOURCE_VERSION=PASS", flush=True)
        if check_tag:
            require_tag(root, expected_tag)
            print("TAGGED_SOURCE_TAG=PASS", flush=True)
        run_project_checks(root)
        print("TAGGED_SOURCE_PUBLIC_SAFETY=PASS", flush=True)
        print("TAGGED_SOURCE_DEPENDENCY_AUDIT=PASS", flush=True)
        print(f"candidate_commit={git_head(root)}", flush=True)
        print("TAGGED_SOURCE_SMOKE=PASS", flush=True)
        return 0
    except SmokeFailure as exc:
        print("TAGGED_SOURCE_SMOKE=FAIL", flush=True)
        print(f"FAILURE_DETAIL={exc}", flush=True)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--expected-version",
        default=RC_VERSION,
    )
    parser.add_argument(
        "--expected-tag",
        default=RC_TAG,
    )
    parser.add_argument(
        "--skip-tag-check",
        action="store_true",
        help="Use only for pre-tag/unit validation; release smoke must check the tag.",
    )
    args = parser.parse_args()

    return run(
        root=args.root.expanduser().resolve(),
        expected_version=args.expected_version,
        expected_tag=args.expected_tag,
        check_tag=not args.skip_tag_check,
    )


if __name__ == "__main__":
    raise SystemExit(main())
