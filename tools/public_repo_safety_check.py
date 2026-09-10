#!/usr/bin/env python3
"""High-confidence public-repository safety checks.

This scanner is intentionally conservative. It catches obviously dangerous tracked
runtime paths and several credential formats with distinctive prefixes. It is not
a replacement for credential rotation, code review, or a full secret-scanning
service.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_TRACKED_PATHS = (
    re.compile(r"^\.env(?:\.|$)", re.IGNORECASE),
    re.compile(r"^chrome_profile(?:/|$)", re.IGNORECASE),
    re.compile(r"^\.uwa(?:/|$)", re.IGNORECASE),
    re.compile(r"(?:^|/)(?:codex[-_]?wire|wire[-_]?trace|responses[-_]?dump)(?:/|$)", re.IGNORECASE),
    re.compile(r"^runtime_state(?:/|$)", re.IGNORECASE),
    re.compile(r"(?:^|/)cookies?(?:[._-].*)?\.json$", re.IGNORECASE),
    re.compile(r"\.(?:sqlite|sqlite3)(?:-shm|-wal)?$", re.IGNORECASE),
    re.compile(r"\.log$", re.IGNORECASE),
)

SECRET_PATTERNS = (
    ("OpenAI-style secret key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{20,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "private key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
            re.IGNORECASE,
        ),
    ),
)

TEXT_SUFFIX_ALLOWLIST = {
    "",
    ".bat",
    ".cfg",
    ".conf",
    ".css",
    ".env",
    ".example",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
    ".zsh",
}


def tracked_files() -> list[str]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
    )
    return [item.decode("utf-8", errors="replace") for item in output.split(b"\0") if item]


def should_scan_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIX_ALLOWLIST and path.is_file()


def main() -> int:
    findings: list[str] = []

    for relative in tracked_files():
        normalized = relative.replace("\\", "/")
        if normalized == ".env.example":
            pass
        elif any(pattern.search(normalized) for pattern in FORBIDDEN_TRACKED_PATHS):
            findings.append(f"forbidden tracked runtime/sensitive path: {normalized}")

        path = ROOT / relative
        if not should_scan_text(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for label, pattern in SECRET_PATTERNS:
            match = pattern.search(text)
            if match:
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{label}: {normalized}:{line}")

    if findings:
        print("Public repository safety check FAILED")
        for finding in findings:
            print(f"  - {finding}")
        print("Rotate/revoke any real credential before cleaning Git history.")
        return 1

    print("Public repository safety check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
