#!/usr/bin/env python3
"""Local S4 release-consistency gate for Codex Web Bridge rc.1."""

from __future__ import annotations

import argparse
import json
import re
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
    "docs/RELEASE_PLAN.md",
    "docs/RELEASE_REQUIREMENTS.md",
    "docs/RELEASE_TECHNICAL_DESIGN.md",
    "docs/RELEASE_TEST_PLAN.md",
    "docs/DESKTOP_E2E_GATE.md",
    "docs/STANDALONE_S3_LIVE_GATE_2026-09-10.md",
    "docs/STANDALONE_S4_INSTALL_SMOKE_2026-09-17.md",
    "CONTRIBUTING.md",
    "docs/README.md",
    "docs/ARCHITECTURE.md",
    "docs/DEVELOPMENT.md",
    "docs/TESTING.md",
    "docs/TROUBLESHOOTING.md",
    "docs/ROADMAP.md",
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
        "S4 = PENDING",
        "CURRENT / LIVE RUN READY",
        "S3 current",
        "post-compaction blocker",
        "remain in progress",
        "release remains in S4 clean-checkout install smoke validation",
    )
    release_docs = [
        "README.md",
        "README.en.md",
        "README.th.md",
        "README.ja.md",
        "README.ko.md",
        "README.zh-CN.md",
        "CHANGELOG.md",
        "docs/RELEASE_PROCESS.md",
        "docs/RELEASE_REQUIREMENTS.md",
        "docs/STANDALONE_S3_LIVE_GATE_2026-09-10.md",
        "docs/STANDALONE_S4_INSTALL_SMOKE_2026-09-17.md",
    ]
    for relative in release_docs:
        text = _read(root, relative)
        for phrase in stale_phrases:
            if phrase.casefold() in text.casefold():
                raise GateFailure("docs_sync", f"stale_text={relative}:{phrase}")


    for relative in (
        "README.md",
        "README.en.md",
        "README.th.md",
        "README.ja.md",
        "README.ko.md",
        "README.zh-CN.md",
    ):
        if "git switch standalone-dev" in _read(root, relative):
            raise GateFailure(
                "docs_sync",
                f"release_quick_start_uses_dev_branch={relative}",
            )


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
    required = ("127.0.0.1", "cors", "unsafe", "conversation url")
    missing = [value for value in required if value not in text]
    if missing:
        raise GateFailure("security", "missing=" + ",".join(missing))

    config_path = root / "config" / "browser_config.json"
    if not config_path.is_file():
        raise GateFailure("security", "missing=config/browser_config.json")
    try:
        browser_config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GateFailure("security", f"browser_config_invalid={type(exc).__name__}") from exc

    tab_pool = browser_config.get("tab_pool")
    if not isinstance(tab_pool, dict):
        raise GateFailure("security", "browser_config_tab_pool_missing")
    if tab_pool.get("excluded_urls") not in ([], None):
        raise GateFailure("security", "tracked_excluded_urls_not_empty")
    if tab_pool.get("route_groups") not in ([], None):
        raise GateFailure("security", "tracked_route_groups_not_empty")
    if tab_pool.get("auto_remember_url_presets") is not False:
        raise GateFailure("security", "tracked_auto_remember_url_presets_not_false")

    raw = config_path.read_text(encoding="utf-8")
    if re.search(
        r"https?://(?:chatgpt\.com|arena\.ai|grok\.com|claude\.ai)"
        r"/c/[A-Za-z0-9_-]{8,}",
        raw,
        re.IGNORECASE,
    ):
        raise GateFailure("security", "tracked_raw_conversation_url")


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


def check_desktop_candidate(root: Path, result_path: Path) -> None:
    if not result_path.is_file():
        raise GateFailure("desktop_candidate_match", "desktop_result_missing")
    values = parse_key_values(result_path.read_text(encoding="utf-8"))
    required = {
        "STANDALONE_DESKTOP_E2E": "PASS",
        "DESKTOP_CONTEXT": "PASS",
        "DESKTOP_LOCAL_TOOLS": "PASS",
        "DESKTOP_ROUTE_UWA_CHATGPT_HIGH": "PASS",
        "DESKTOP_REQUEST_MANAGER_CLEAN": "PASS",
    }
    for key, expected in required.items():
        if values.get(key) != expected:
            raise GateFailure(
                "desktop_candidate_match",
                f"{key.lower()}_not_{expected.lower()}",
            )
    if values.get("candidate_commit", "") != git_head(root):
        raise GateFailure("desktop_candidate_match", "candidate_sha_mismatch")


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
    desktop_result: Path,
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
        check_desktop_candidate(root, desktop_result)
        print("S4_DESKTOP_E2E_CANDIDATE_MATCH=PASS", flush=True)
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
        "--desktop-result",
        type=Path,
        default=Path.home() / ".uwa" / "standalone-desktop-e2e" / "result.txt",
    )
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
        desktop_result=args.desktop_result.expanduser(),
        install_smoke_result=args.install_smoke_result.expanduser(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
