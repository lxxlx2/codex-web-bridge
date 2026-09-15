#!/usr/bin/env python3
"""Local S4 release-consistency gate for Codex Web Bridge rc.1."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


RC_VERSION = "0.1.0-rc.1"
RC_TAG = "v0.1.0-rc.1"
REQUIRED_DOCS = (
    "README.md",
    "README.en.md",
    "README.th.md",
    "README.ja.md",
    "README.ko.md",
    "README.zh-CN.md",
    "CHANGELOG.md",
    "LICENSE",
    "NOTICE.md",
    "SECURITY.md",
    "VERSION",
    "docs/RELEASE_PROCESS.md",
    "docs/RELEASE_REQUIREMENTS.md",
    "docs/RELEASE_TECHNICAL_DESIGN.md",
    "docs/RELEASE_TEST_PLAN.md",
)


class GateFailure(RuntimeError):
    def __init__(self, gate: str, detail: str) -> None:
        super().__init__(detail)
        self.gate = gate
        self.detail = detail


def _read(root: Path, relative: str) -> str:
    path = root / relative
    if not path.is_file():
        raise GateFailure("docs_sync", f"missing={relative}")
    return path.read_text(encoding="utf-8")


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        raise GateFailure("git", f"command_failed={' '.join(args)}")
    return result.stdout.strip()


def git_head(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD")


def require_clean_worktree(root: Path) -> None:
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise GateFailure("worktree", "dirty")


def check_docs(root: Path) -> None:
    for relative in REQUIRED_DOCS:
        _read(root, relative)

    approvals = {
        "docs/RELEASE_REQUIREMENTS.md": "REQUIREMENTS_APPROVED=YES",
        "docs/RELEASE_TECHNICAL_DESIGN.md": "TECH_DESIGN_APPROVED=YES",
        "docs/RELEASE_TEST_PLAN.md": "TEST_PLAN_APPROVED=YES",
    }
    for relative, marker in approvals.items():
        if marker not in _read(root, relative):
            raise GateFailure("docs_sync", f"missing_marker={relative}:{marker}")

    stale_phrases = (
        "S3 = OPEN",
        "S3 current",
        "post-compaction blocker",
        "remain in progress",
    )
    release_docs = [
        "README.md",
        "README.en.md",
        "README.th.md",
        "README.ja.md",
        "README.ko.md",
        "README.zh-CN.md",
        "CHANGELOG.md",
    ]
    for relative in release_docs:
        text = _read(root, relative)
        for phrase in stale_phrases:
            if phrase.casefold() in text.casefold():
                raise GateFailure("docs_sync", f"stale_text={relative}:{phrase}")


def check_version(root: Path) -> None:
    version = _read(root, "VERSION").strip()
    if version != RC_VERSION:
        raise GateFailure("version_sync", f"version={version or 'EMPTY'}")
    changelog = _read(root, "CHANGELOG.md")
    if RC_VERSION not in changelog and RC_TAG not in changelog:
        raise GateFailure("version_sync", "changelog_missing_rc_version")
    release_process = _read(root, "docs/RELEASE_PROCESS.md")
    if RC_TAG not in release_process:
        raise GateFailure("version_sync", "release_process_missing_tag")


def check_security(root: Path) -> None:
    text = _read(root, "SECURITY.md").casefold()
    required = ("127.0.0.1", "cors", "unsafe")
    missing = [value for value in required if value not in text]
    if missing:
        raise GateFailure("security", "missing=" + ",".join(missing))


def check_provenance(root: Path) -> None:
    notice = _read(root, "NOTICE.md")
    required = (
        "lumingya/universal-web-api",
        "lxxlx2/universal-web-api",
        "leeguooooo/chatgpt-use",
        "kev489/gpt-tool-use",
    )
    missing = [value for value in required if value not in notice]
    if missing:
        raise GateFailure("provenance", "missing=" + ",".join(missing))


def parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def latest_s3_result(private_root: Path) -> Path:
    matches = sorted(
        private_root.expanduser().glob("*/result.txt"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not matches:
        raise GateFailure("s3_candidate_match", "s3_result_missing")
    return matches[0]


def check_s3_candidate(root: Path, result_path: Path) -> None:
    values = parse_key_values(result_path.read_text(encoding="utf-8"))
    if values.get("STANDALONE_S3") != "PASS_LIVE_CLOSED":
        raise GateFailure("s3_candidate_match", "s3_not_closed")
    expected = git_head(root)
    actual = values.get("candidate_commit", "")
    if actual != expected:
        raise GateFailure("s3_candidate_match", "candidate_sha_mismatch")


def check_install_smoke(
    result_path: Path,
    *,
    expected_candidate: str | None = None,
) -> None:
    if not result_path.is_file():
        raise GateFailure("install_smoke", "result_missing")
    values = parse_key_values(result_path.read_text(encoding="utf-8"))
    required = {
        "INSTALL_SMOKE": "PASS",
        "OFFICIAL_ROLLBACK": "PASS",
        "BASIC_CODEX_REQUEST": "PASS",
        "AUTH": "UNCHANGED",
        "WRAPPER_ROOT": "PASS",
        "LISTENER_OWNERSHIP": "PASS",
    }
    for key, expected in required.items():
        if values.get(key) != expected:
            gate = "official_rollback" if key == "OFFICIAL_ROLLBACK" else "install_smoke"
            raise GateFailure(gate, f"{key.lower()}_not_{expected.lower()}")
    if expected_candidate is not None:
        if values.get("candidate_commit", "") != expected_candidate:
            raise GateFailure("install_smoke", "candidate_sha_mismatch")


def run(
    *,
    root: Path,
    s3_result: Path,
    install_smoke_result: Path,
) -> int:
    try:
        require_clean_worktree(root)
        check_docs(root)
        print("S4_DOCS_SYNC=PASS", flush=True)
        check_version(root)
        print("S4_VERSION_SYNC=PASS", flush=True)
        check_security(root)
        print("S4_SECURITY_CHECK=PASS", flush=True)
        check_provenance(root)
        print("S4_PROVENANCE_CHECK=PASS", flush=True)
        candidate = git_head(root)
        check_install_smoke(
            install_smoke_result,
            expected_candidate=candidate,
        )
        print("S4_INSTALL_SMOKE=PASS", flush=True)
        print("S4_OFFICIAL_ROLLBACK=PASS", flush=True)
        check_s3_candidate(root, s3_result)
        print("S4_S3_CANDIDATE_MATCH=PASS", flush=True)
        print("STANDALONE_S4_LOCAL=PASS", flush=True)
        return 0
    except GateFailure as exc:
        print("STANDALONE_S4_LOCAL=FAIL", flush=True)
        print(f"FAILURE_CLASS={exc.gate}", flush=True)
        print(f"FAILURE_DETAIL={exc.detail}", flush=True)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--private-root",
        type=Path,
        default=Path.home() / ".uwa" / "standalone-s3",
    )
    parser.add_argument("--s3-result", type=Path)
    parser.add_argument(
        "--install-smoke-result",
        type=Path,
        default=Path.home() / ".uwa" / "standalone-s4" / "install-smoke-result.txt",
    )
    args = parser.parse_args()

    s3_result = args.s3_result or latest_s3_result(args.private_root)
    return run(
        root=args.root.expanduser().resolve(),
        s3_result=s3_result.expanduser(),
        install_smoke_result=args.install_smoke_result.expanduser(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
