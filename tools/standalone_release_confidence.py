#!/usr/bin/env python3
"""Aggregate candidate-bound reliability evidence before S4.

This gate does not contact ChatGPT Web and does not rerun any acceptance task.
It validates already-produced private evidence for the exact current commit.

Release confidence for v0.1.0-rc.1 requires:
- at least three successful full S3 runs on the same candidate;
- those S3 successes must span at least two two-hour UTC windows;
- one successful office-work soak on the same candidate.

External failures such as rate limiting are neither counted as success nor
treated as evidence that the candidate code is wrong. They simply do not satisfy
this positive evidence gate.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


MIN_S3_PASS_COUNT = 3
MIN_S3_TIME_WINDOWS = 2
MIN_S3_SPAN_SECONDS = 2 * 60 * 60
S3_WINDOW_SECONDS = 2 * 60 * 60
DEFAULT_S3_ROOT = Path.home() / ".uwa" / "standalone-s3"
DEFAULT_SOAK_ROOT = Path.home() / ".uwa" / "standalone-office-soak"
DEFAULT_RESULT = Path.home() / ".uwa" / "standalone-release-confidence" / "result.txt"
_STAMP_RE = re.compile(r"^(\d{8}T\d{6}Z)")


class GateFailure(RuntimeError):
    def __init__(self, gate: str, detail: str = "") -> None:
        super().__init__(detail or gate)
        self.gate = gate
        self.detail = detail


def _git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise GateFailure("git_head", "unable_to_resolve_candidate_commit")
    return result.stdout.strip()


def _assert_candidate_stable(
    root: Path,
    expected_candidate: str,
) -> None:
    if _git_head(root) != expected_candidate:
        raise GateFailure(
            "release_confidence_candidate",
            "candidate_sha_changed",
        )
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=str(root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if status.returncode != 0:
        raise GateFailure(
            "release_confidence_candidate",
            "git_status_failed",
        )
    if status.stdout.strip():
        raise GateFailure(
            "release_confidence_candidate",
            "worktree_changed",
        )


def parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _timestamp_from_result_path(path: Path) -> float | None:
    match = _STAMP_RE.match(path.parent.name)
    if match is None:
        return None
    try:
        value = datetime.strptime(
            match.group(1),
            "%Y%m%dT%H%M%SZ",
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return value.timestamp()


def successful_s3_results(
    private_root: Path,
    *,
    candidate: str,
) -> list[tuple[Path, float]]:
    matches: list[tuple[Path, float]] = []
    root = private_root.expanduser()

    for path in root.glob("*/result.txt"):
        try:
            values = parse_key_values(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if values.get("STANDALONE_S3") != "PASS_LIVE_CLOSED":
            continue
        if values.get("candidate_commit") != candidate:
            continue
        timestamp = _timestamp_from_result_path(path)
        if timestamp is None:
            continue
        matches.append((path, timestamp))

    matches.sort(key=lambda item: item[1])
    return matches


def s3_time_windows(results: list[tuple[Path, float]]) -> set[int]:
    return {
        int(timestamp // S3_WINDOW_SECONDS)
        for _path, timestamp in results
    }


def check_s3_stability(
    private_root: Path,
    *,
    candidate: str,
    min_passes: int = MIN_S3_PASS_COUNT,
    min_windows: int = MIN_S3_TIME_WINDOWS,
    min_span_seconds: int = MIN_S3_SPAN_SECONDS,
) -> tuple[int, int, int]:
    results = successful_s3_results(
        private_root,
        candidate=candidate,
    )
    pass_count = len(results)
    window_count = len(s3_time_windows(results))
    span_seconds = (
        int(results[-1][1] - results[0][1])
        if len(results) >= 2
        else 0
    )

    if pass_count < min_passes:
        raise GateFailure(
            "release_confidence_s3",
            f"pass_count={pass_count} required={min_passes}",
        )
    if window_count < min_windows:
        raise GateFailure(
            "release_confidence_s3",
            f"time_windows={window_count} required={min_windows}",
        )
    if span_seconds < min_span_seconds:
        raise GateFailure(
            "release_confidence_s3",
            f"span_seconds={span_seconds} required={min_span_seconds}",
        )
    return pass_count, window_count, span_seconds


def latest_successful_office_soak(
    root: Path,
    *,
    candidate: str,
) -> Path:
    matches = sorted(
        root.expanduser().glob("*/result.txt"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in matches:
        try:
            values = parse_key_values(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if values.get("STANDALONE_OFFICE_SOAK") != "PASS":
            continue
        if values.get("candidate_commit") != candidate:
            continue
        return path
    raise GateFailure(
        "release_confidence_office_soak",
        "successful_result_missing",
    )


def check_office_soak(
    result_path: Path,
    *,
    candidate: str,
) -> None:
    if not result_path.is_file():
        raise GateFailure("release_confidence_office_soak", "result_missing")
    values = parse_key_values(result_path.read_text(encoding="utf-8"))
    required = {
        "STANDALONE_OFFICE_SOAK": "PASS",
        "OFFICE_SOAK_CONTEXT": "PASS",
        "OFFICE_SOAK_MULTI_FILE": "PASS",
        "OFFICE_SOAK_FAILURE_RECOVERY": "PASS",
        "OFFICE_SOAK_GIT_DIFF": "PASS",
        "OFFICE_SOAK_INTERACTIVE": "PASS",
        "OFFICE_SOAK_EFFECT_VERIFICATION": "PASS",
        "OFFICE_SOAK_ROUTE_UWA_CHATGPT_HIGH": "PASS",
        "OFFICE_SOAK_REQUEST_MANAGER_CLEAN": "PASS",
        "OFFICE_SOAK_REPOSITORY_CLEAN": "PASS",
    }
    for key, expected in required.items():
        if values.get(key) != expected:
            raise GateFailure(
                "release_confidence_office_soak",
                f"{key.lower()}_not_{expected.lower()}",
            )
    if values.get("candidate_commit") != candidate:
        raise GateFailure(
            "release_confidence_office_soak",
            "candidate_sha_mismatch",
        )


def _write_result(
    path: Path,
    *,
    candidate: str,
    s3_pass_count: int,
    s3_window_count: int,
    s3_span_seconds: int,
) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(
        "STANDALONE_RELEASE_CONFIDENCE=PASS\n"
        f"RELEASE_CONFIDENCE_S3_PASS_COUNT={s3_pass_count}\n"
        f"RELEASE_CONFIDENCE_S3_TIME_WINDOWS={s3_window_count}\n"
        f"RELEASE_CONFIDENCE_S3_SPAN_SECONDS={s3_span_seconds}\n"
        "RELEASE_CONFIDENCE_OFFICE_SOAK=PASS\n"
        f"candidate_commit={candidate}\n",
        encoding="utf-8",
    )
    try:
        path.parent.chmod(0o700)
        path.chmod(0o600)
    except OSError:
        pass


def run(
    *,
    root: Path,
    s3_root: Path,
    office_soak_result: Path | None,
    office_soak_root: Path,
    result_path: Path,
) -> int:
    try:
        candidate = _git_head(root)
        pass_count, window_count, span_seconds = check_s3_stability(
            s3_root,
            candidate=candidate,
        )
        print(
            f"RELEASE_CONFIDENCE_S3_PASS_COUNT={pass_count}",
            flush=True,
        )
        print(
            f"RELEASE_CONFIDENCE_S3_TIME_WINDOWS={window_count}",
            flush=True,
        )
        print(
            f"RELEASE_CONFIDENCE_S3_SPAN_SECONDS={span_seconds}",
            flush=True,
        )

        selected_soak = (
            office_soak_result
            if office_soak_result is not None
            else latest_successful_office_soak(
                office_soak_root,
                candidate=candidate,
            )
        )
        check_office_soak(
            selected_soak,
            candidate=candidate,
        )
        print("RELEASE_CONFIDENCE_OFFICE_SOAK=PASS", flush=True)

        _assert_candidate_stable(
            root,
            candidate,
        )
        _write_result(
            result_path,
            candidate=candidate,
            s3_pass_count=pass_count,
            s3_window_count=window_count,
            s3_span_seconds=span_seconds,
        )
        print("STANDALONE_RELEASE_CONFIDENCE=PASS", flush=True)
        print(f"candidate_commit={candidate}", flush=True)
        return 0
    except GateFailure as exc:
        print("STANDALONE_RELEASE_CONFIDENCE=FAIL", flush=True)
        print(f"FAILURE_CLASS={exc.gate}", flush=True)
        if exc.detail:
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
        "--s3-root",
        type=Path,
        default=DEFAULT_S3_ROOT,
    )
    parser.add_argument(
        "--office-soak-result",
        type=Path,
    )
    parser.add_argument(
        "--office-soak-root",
        type=Path,
        default=DEFAULT_SOAK_ROOT,
    )
    parser.add_argument(
        "--result",
        type=Path,
        default=DEFAULT_RESULT,
    )
    args = parser.parse_args()

    return run(
        root=args.root.expanduser().resolve(),
        s3_root=args.s3_root.expanduser(),
        office_soak_result=(
            args.office_soak_result.expanduser()
            if args.office_soak_result is not None
            else None
        ),
        office_soak_root=args.office_soak_root.expanduser(),
        result_path=args.result.expanduser(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
