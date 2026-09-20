"""Deterministic tests for the release-confidence evidence aggregator."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import standalone_release_confidence as confidence


def _stamp_result(
    root: Path,
    stamp: str,
    *,
    candidate: str,
    status: str = "PASS_LIVE_CLOSED",
) -> Path:
    path = root / stamp / "result.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"STANDALONE_S3={status}\n"
        f"candidate_commit={candidate}\n",
        encoding="utf-8",
    )
    return path


def _soak(path: Path, *, candidate: str, status: str = "PASS") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"STANDALONE_OFFICE_SOAK={status}\n"
        f"OFFICE_SOAK_CONTEXT={status}\n"
        f"OFFICE_SOAK_MULTI_FILE={status}\n"
        f"OFFICE_SOAK_FAILURE_RECOVERY={status}\n"
        f"OFFICE_SOAK_GIT_DIFF={status}\n"
        f"OFFICE_SOAK_INTERACTIVE={status}\n"
        f"OFFICE_SOAK_EFFECT_VERIFICATION={status}\n"
        f"OFFICE_SOAK_ROUTE_UWA_CHATGPT_HIGH={status}\n"
        f"OFFICE_SOAK_REQUEST_MANAGER_CLEAN={status}\n"
        f"OFFICE_SOAK_REPOSITORY_CLEAN={status}\n"
        f"candidate_commit={candidate}\n",
        encoding="utf-8",
    )
    return path


def test_successful_s3_results_filter_status_and_candidate(tmp_path: Path):
    _stamp_result(tmp_path, "20260921T000000Z", candidate="abc")
    _stamp_result(tmp_path, "20260921T003000Z", candidate="other")
    _stamp_result(
        tmp_path,
        "20260921T010000Z",
        candidate="abc",
        status="FAIL",
    )

    results = confidence.successful_s3_results(
        tmp_path,
        candidate="abc",
    )

    assert [path.parent.name for path, _ in results] == [
        "20260921T000000Z"
    ]


def test_s3_stability_requires_three_exact_candidate_passes(tmp_path: Path):
    _stamp_result(tmp_path, "20260921T000000Z", candidate="abc")
    _stamp_result(tmp_path, "20260921T020000Z", candidate="abc")

    with pytest.raises(
        confidence.GateFailure,
        match="pass_count=2 required=3",
    ):
        confidence.check_s3_stability(
            tmp_path,
            candidate="abc",
        )


def test_s3_stability_requires_two_time_windows(tmp_path: Path):
    _stamp_result(tmp_path, "20260921T000000Z", candidate="abc")
    _stamp_result(tmp_path, "20260921T001000Z", candidate="abc")
    _stamp_result(tmp_path, "20260921T005000Z", candidate="abc")

    with pytest.raises(
        confidence.GateFailure,
        match="time_windows=1 required=2",
    ):
        confidence.check_s3_stability(
            tmp_path,
            candidate="abc",
        )


def test_s3_stability_accepts_three_passes_across_two_windows(tmp_path: Path):
    _stamp_result(tmp_path, "20260921T000000Z", candidate="abc")
    _stamp_result(tmp_path, "20260921T010000Z", candidate="abc")
    _stamp_result(tmp_path, "20260921T021000Z", candidate="abc")

    pass_count, windows = confidence.check_s3_stability(
        tmp_path,
        candidate="abc",
    )

    assert pass_count == 3
    assert windows == 2


def test_office_soak_requires_all_markers_and_same_candidate(tmp_path: Path):
    result = _soak(tmp_path / "soak.txt", candidate="abc")
    confidence.check_office_soak(
        result,
        candidate="abc",
    )

    bad = _soak(tmp_path / "bad.txt", candidate="old")
    with pytest.raises(
        confidence.GateFailure,
        match="candidate_sha_mismatch",
    ):
        confidence.check_office_soak(
            bad,
            candidate="abc",
        )


def test_run_writes_candidate_bound_confidence_result(
    tmp_path: Path,
    monkeypatch,
):
    s3_root = tmp_path / "s3"
    _stamp_result(s3_root, "20260921T000000Z", candidate="abc")
    _stamp_result(s3_root, "20260921T010000Z", candidate="abc")
    _stamp_result(s3_root, "20260921T021000Z", candidate="abc")

    soak = _soak(tmp_path / "soak" / "result.txt", candidate="abc")
    out = tmp_path / "confidence" / "result.txt"
    monkeypatch.setattr(confidence, "_git_head", lambda root: "abc")

    rc = confidence.run(
        root=tmp_path,
        s3_root=s3_root,
        office_soak_result=soak,
        result_path=out,
    )

    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "STANDALONE_RELEASE_CONFIDENCE=PASS" in text
    assert "RELEASE_CONFIDENCE_S3_PASS_COUNT=3" in text
    assert "RELEASE_CONFIDENCE_S3_TIME_WINDOWS=2" in text
    assert "RELEASE_CONFIDENCE_OFFICE_SOAK=PASS" in text
    assert "candidate_commit=abc" in text
