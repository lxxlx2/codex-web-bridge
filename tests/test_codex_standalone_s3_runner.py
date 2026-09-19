from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import standalone_s3_live_acceptance as s3


class StandaloneS3RunnerTests(unittest.TestCase):
    def test_cli_imports_without_running_live_gate(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(TOOLS / "standalone_s3_live_acceptance.py"),
                "--help",
            ],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Release-grade standalone S3 acceptance", result.stdout)

    def test_codex_jsonl_parser_keeps_only_gate_metadata(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "private-thread"},
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "printf private-body",
                    "aggregated_output": "private-output",
                },
            },
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "CONTEXT_PASS"},
            },
            {"type": "turn.completed", "usage": {"input_tokens": 999}},
        ]
        raw = "\n".join(json.dumps(item) for item in events)
        observation = s3._parse_codex_jsonl(raw, 0)

        self.assertEqual(observation.returncode, 0)
        self.assertEqual(observation.thread_ids, ["private-thread"])
        self.assertEqual(observation.command_count, 1)
        self.assertEqual(observation.final_message, "CONTEXT_PASS")
        self.assertEqual(observation.turn_completed_count, 1)
        self.assertFalse(hasattr(observation, "commands"))
        self.assertFalse(hasattr(observation, "usage"))

    def test_probe_trigger_reply_accepts_exact_or_deferred(self) -> None:
        self.assertTrue(
            s3._probe_trigger_reply_acceptable(
                {
                    "TRIGGER_REPLY_EXACT": "YES",
                    "TRIGGER_REPLY_DEFERRED_TO_POST_COMPACTION_RECOVERY": "NO",
                }
            )
        )
        self.assertTrue(
            s3._probe_trigger_reply_acceptable(
                {
                    "TRIGGER_REPLY_EXACT": "NO",
                    "TRIGGER_REPLY_DEFERRED_TO_POST_COMPACTION_RECOVERY": "YES",
                }
            )
        )
        self.assertFalse(
            s3._probe_trigger_reply_acceptable(
                {
                    "TRIGGER_REPLY_EXACT": "NO",
                    "TRIGGER_REPLY_DEFERRED_TO_POST_COMPACTION_RECOVERY": "NO",
                }
            )
        )

    def test_remote_normalization_recognizes_integrated_origin(self) -> None:
        self.assertEqual(
            s3._normalize_remote("git@github.com:lxxlx2/universal-web-api.git"),
            "https://github.com/lxxlx2/universal-web-api",
        )

    def test_surface_preflight_parser_requires_exactly_one_sanitized_row(self) -> None:
        payload = {
            "ok": True,
            "failure_class": "none",
            "surface_kind": "chat",
            "composer_empty": True,
        }
        parsed = s3._parse_surface_preflight(
            "noise\nSURFACE_PREFLIGHT_JSON=" + json.dumps(payload) + "\n"
        )
        self.assertEqual(parsed, payload)

        with self.assertRaises(s3.GateFailure):
            s3._parse_surface_preflight("no result\n")

    def test_desktop_running_prefers_native_macos_application_state(self) -> None:
        completed = subprocess.CompletedProcess(
            ["osascript"],
            0,
            stdout="true\n",
            stderr="",
        )
        with (
            patch.object(s3.sys, "platform", "darwin"),
            patch.object(s3.subprocess, "run", return_value=completed) as run_mock,
        ):
            self.assertTrue(s3._codex_desktop_running())
            self.assertEqual(
                run_mock.call_args.args[0],
                ["osascript", "-e", 'application "Codex" is running'],
            )

    def test_quiet_desktop_returns_whether_runner_changed_app_state(self) -> None:
        with (
            patch.object(s3, "_codex_desktop_running", return_value=False),
            patch.object(s3.subprocess, "run") as run_mock,
        ):
            self.assertFalse(s3._quiet_codex_desktop())
            run_mock.assert_not_called()

        with (
            patch.object(s3, "_codex_desktop_running", return_value=True),
            patch.object(s3.subprocess, "run") as run_mock,
            patch.object(s3.time, "sleep"),
        ):
            self.assertTrue(s3._quiet_codex_desktop())
            self.assertEqual(run_mock.call_args.args[0][0:2], ["osascript", "-e"])

    def test_restore_desktop_only_when_gate_quieted_running_app(self) -> None:
        with (
            patch.object(s3.sys, "platform", "darwin"),
            patch.object(s3.subprocess, "run") as run_mock,
        ):
            s3._restore_codex_desktop(False)
            run_mock.assert_not_called()

            s3._restore_codex_desktop(True)
            run_mock.assert_called_once()
            self.assertEqual(run_mock.call_args.args[0], ["open", "-a", "Codex"])

    def test_surface_failure_stops_before_core_live_gate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            private_root = Path(raw) / "private"
            acceptance_root = Path(raw) / "acceptance"

            with (
                patch.object(s3.core, "_preflight_repo"),
                patch.object(s3, "_candidate_commit", return_value="a" * 40),
                patch.object(s3.core, "_configure_uwa_route"),
                patch.object(s3.core, "_start_standalone_listener", return_value="STARTED"),
                patch.object(s3.core, "_health_ready", return_value={}),
                patch.object(s3.core, "_validation_python", return_value=sys.executable),
                patch.object(s3, "_quiet_codex_desktop"),
                patch.object(s3.core, "_wait_request_cleanup"),
                patch.object(s3, "_reset_acceptance_chatgpt_target"),
                patch.object(
                    s3,
                    "_run_surface_preflight",
                    side_effect=s3.GateFailure(
                        "chatgpt_work_quota_exhausted",
                        "work_quota_exhausted",
                    ),
                ),
                patch.object(s3.core, "run") as core_run,
            ):
                rc = s3.run(
                    acceptance_root=acceptance_root,
                    private_root=private_root,
                    turn_timeout_sec=60,
                    compaction_timeout_sec=60,
                )

            self.assertEqual(rc, 1)
            core_run.assert_not_called()
            results = list(private_root.glob("*/result.txt"))
            self.assertEqual(len(results), 1)
            text = results[0].read_text(encoding="utf-8")
            self.assertIn(
                "FAILURE_CLASS=chatgpt_work_quota_exhausted",
                text,
            )
            self.assertIn("candidate_commit=" + "a" * 40, text)

    def test_passive_surface_recheck_fails_closed_on_work(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            private_dir = Path(raw)
            payload = {
                "chatgpt_web": {
                    "surface": {
                        "surface_kind": "work",
                        "surface_ready": False,
                        "pathname_class": "root",
                        "composer_empty": True,
                        "blocking_reason": "work_surface",
                    }
                }
            }
            with patch.object(s3.core, "_health_ready", return_value=payload):
                with self.assertRaises(s3.GateFailure) as ctx:
                    s3._passive_surface_recheck(private_dir)
            self.assertEqual(ctx.exception.gate, "chatgpt_work_surface")

    def test_mid_run_rate_limit_is_promoted_and_acknowledgement_is_cleaned(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            private_dir = Path(raw)
            payload = {
                "chatgpt_web": {
                    "surface": {
                        "surface_kind": "chat",
                        "surface_ready": False,
                        "pathname_class": "conversation",
                        "composer_empty": True,
                        "blocking_reason": "rate_limited",
                    }
                }
            }
            cleanup_result = {
                "ok": True,
                "dismissed": True,
                "target_count": 1,
                "surface_kind": "chat",
                "composer_empty": True,
                "blocking_reason": "none",
            }
            with (
                patch.object(s3.core, "_health_ready", return_value=payload),
                patch.object(
                    s3.surface_preflight,
                    "dismiss_rate_limit_notice_in_place",
                    return_value=cleanup_result,
                ) as cleanup_mock,
            ):
                failure = s3._external_surface_failure_after_core_failure(private_dir)

            self.assertIsNotNone(failure)
            assert failure is not None
            self.assertEqual(failure.gate, "chatgpt_web_rate_limited")
            self.assertEqual(failure.detail, "rate_limited")
            cleanup_mock.assert_called_once_with(timeout_seconds=12.0)

            cleanup = json.loads(
                (private_dir / "rate-limit-failure-cleanup.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(cleanup["dismissed"])
            self.assertTrue(cleanup["ok"])
            self.assertEqual(cleanup["blocking_reason"], "none")

    def test_mid_run_rate_limit_cleanup_failure_does_not_mask_external_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            private_dir = Path(raw)
            payload = {
                "chatgpt_web": {
                    "surface": {
                        "surface_kind": "chat",
                        "surface_ready": False,
                        "pathname_class": "conversation",
                        "composer_empty": True,
                        "blocking_reason": "rate_limited",
                    }
                }
            }
            with (
                patch.object(s3.core, "_health_ready", return_value=payload),
                patch.object(
                    s3.surface_preflight,
                    "dismiss_rate_limit_notice_in_place",
                    side_effect=RuntimeError("browser cleanup failed"),
                ),
            ):
                failure = s3._external_surface_failure_after_core_failure(private_dir)

            self.assertIsNotNone(failure)
            assert failure is not None
            self.assertEqual(failure.gate, "chatgpt_web_rate_limited")

            cleanup = json.loads(
                (private_dir / "rate-limit-failure-cleanup.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(cleanup["dismissed"])
            self.assertFalse(cleanup["ok"])
            self.assertEqual(cleanup["blocking_reason"], "cleanup_exception")
            self.assertEqual(cleanup["error_type"], "RuntimeError")

    def test_mid_run_unknown_surface_does_not_mask_core_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            private_dir = Path(raw)
            payload = {
                "chatgpt_web": {
                    "surface": {
                        "surface_kind": "unknown",
                        "surface_ready": False,
                        "pathname_class": "conversation",
                        "composer_empty": True,
                        "blocking_reason": "unknown_surface",
                    }
                }
            }
            with patch.object(s3.core, "_health_ready", return_value=payload):
                failure = s3._external_surface_failure_after_core_failure(private_dir)
            self.assertIsNone(failure)

    def test_core_result_is_promoted_with_candidate_sha(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            outer = Path(raw)
            inner = outer / "core-run"
            inner.mkdir()
            (inner / "result.txt").write_text(
                "STANDALONE_S3=PASS_LIVE_CLOSED\n"
                "provider=uwa\n"
                "model=chatgpt\n"
                "effort=high\n",
                encoding="utf-8",
            )

            s3._promote_core_result(
                outer_private_dir=outer,
                candidate_commit="b" * 40,
                core_rc=0,
            )

            text = (outer / "result.txt").read_text(encoding="utf-8")
            self.assertIn("STANDALONE_S3=PASS_LIVE_CLOSED", text)
            self.assertIn("candidate_commit=" + "b" * 40, text)


    def test_rate_limit_cooldown_waits_then_rechecks_surface(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            private_dir = Path(raw)

            with (
                patch.object(s3.time, "sleep") as sleep_mock,
                patch.object(
                    s3,
                    "_passive_surface_recheck",
                    return_value={"blocking_reason": "none"},
                ) as recheck_mock,
                patch.object(
                    s3.time,
                    "monotonic",
                    side_effect=[100.0, 103.0],
                ),
            ):
                s3._cooldown_after_rate_limit_notice(
                    private_dir,
                    seconds=3,
                )

            sleep_mock.assert_called_once_with(3)
            recheck_mock.assert_called_once_with(private_dir)
            payload = json.loads(
                (private_dir / "rate-limit-cooldown.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(payload["configured_seconds"], 3)
            self.assertEqual(payload["surface_recheck"], "pass")

    def test_live_gate_cools_down_when_preflight_dismissed_rate_limit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            private_root = Path(raw) / "private"
            acceptance_root = Path(raw) / "acceptance"

            with (
                patch.object(s3.core, "_preflight_repo"),
                patch.object(s3, "_candidate_commit", return_value="c" * 40),
                patch.object(s3.core, "_configure_uwa_route"),
                patch.object(
                    s3.core,
                    "_start_standalone_listener",
                    return_value="STARTED",
                ),
                patch.object(s3.core, "_health_ready", return_value={}),
                patch.object(
                    s3.core,
                    "_validation_python",
                    return_value=sys.executable,
                ),
                patch.object(
                    s3,
                    "_quiet_codex_desktop",
                    return_value=False,
                ),
                patch.object(s3.core, "_wait_request_cleanup"),
                patch.object(s3, "_reset_acceptance_chatgpt_target"),
                patch.object(
                    s3,
                    "_run_surface_preflight",
                    return_value={
                        "ok": True,
                        "actions": [
                            "dismiss_rate_limit_notice",
                            "new_chat",
                        ],
                    },
                ),
                patch.object(
                    s3,
                    "_cooldown_after_rate_limit_notice",
                ) as cooldown_mock,
                patch.object(s3.core, "_restart_standalone_listener"),
                patch.object(
                    s3,
                    "_passive_surface_recheck",
                    return_value={"blocking_reason": "none"},
                ),
                patch.object(s3.core, "run", return_value=0),
                patch.object(s3, "_promote_core_result"),
                patch.object(s3, "_restore_codex_desktop"),
            ):
                rc = s3.run(
                    acceptance_root=acceptance_root,
                    private_root=private_root,
                    turn_timeout_sec=60,
                    compaction_timeout_sec=60,
                )

            self.assertEqual(rc, 0)
            cooldown_mock.assert_called_once()


    def test_compaction_cooldown_waits_then_preserves_thread_surface(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            private_dir = Path(raw)

            with (
                patch.object(
                    s3.core.time,
                    "sleep",
                ) as sleep_mock,
                patch.object(
                    s3.core.time,
                    "monotonic",
                    side_effect=[200.0, 203.0],
                ),
                patch.object(
                    s3.core.surface_preflight,
                    "dismiss_rate_limit_notice_in_place",
                    return_value={
                        "ok": True,
                        "dismissed": True,
                        "target_count": 1,
                        "surface_kind": "chat",
                        "composer_empty": True,
                        "blocking_reason": "none",
                    },
                ) as cleanup_mock,
            ):
                s3.core._cooldown_after_compaction_probe(
                    private_dir,
                    seconds=3,
                )

            sleep_mock.assert_called_once_with(3)
            cleanup_mock.assert_called_once_with(
                timeout_seconds=12.0,
            )
            payload = json.loads(
                (private_dir / "compaction-cooldown.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(payload["configured_seconds"], 3)
            self.assertTrue(payload["dismissed_rate_limit_notice"])
            self.assertEqual(payload["blocking_reason"], "none")
            self.assertTrue(payload["ok"])

    def test_compaction_cooldown_fails_closed_when_surface_still_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            private_dir = Path(raw)

            with (
                patch.object(
                    s3.core.time,
                    "sleep",
                ),
                patch.object(
                    s3.core.time,
                    "monotonic",
                    side_effect=[300.0, 303.0],
                ),
                patch.object(
                    s3.core.surface_preflight,
                    "dismiss_rate_limit_notice_in_place",
                    return_value={
                        "ok": False,
                        "dismissed": True,
                        "target_count": 1,
                        "surface_kind": "chat",
                        "composer_empty": True,
                        "blocking_reason": "rate_limited",
                    },
                ),
            ):
                with self.assertRaises(s3.GateFailure) as ctx:
                    s3.core._cooldown_after_compaction_probe(
                        private_dir,
                        seconds=3,
                    )

            self.assertEqual(
                ctx.exception.gate,
                "compaction_cooldown",
            )
            self.assertEqual(
                ctx.exception.detail,
                "rate_limited",
            )


    def test_recent_rate_limit_marker_waits_remaining_window(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            private_root = Path(raw)

            with patch.object(s3.time, "time", return_value=1000.0):
                s3._record_rate_limit_marker(private_root)

            with (
                patch.object(s3.time, "time", return_value=1060.0),
                patch.object(s3.time, "sleep") as sleep_mock,
            ):
                remaining = s3._recent_rate_limit_remaining_seconds(
                    private_root,
                    cooldown_seconds=180,
                )
                self.assertEqual(remaining, 120.0)
                with patch.object(
                    s3,
                    "_recent_rate_limit_remaining_seconds",
                    return_value=remaining,
                ):
                    s3._wait_for_recent_rate_limit_window(
                        private_root,
                    )

            sleep_mock.assert_called_once_with(120.0)

    def test_expired_recent_rate_limit_marker_does_not_wait(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            private_root = Path(raw)

            with patch.object(s3.time, "time", return_value=1000.0):
                s3._record_rate_limit_marker(private_root)

            with (
                patch.object(s3.time, "time", return_value=1300.0),
                patch.object(s3.time, "sleep") as sleep_mock,
            ):
                remaining = s3._recent_rate_limit_remaining_seconds(
                    private_root,
                    cooldown_seconds=180,
                )

            self.assertEqual(remaining, 0.0)
            sleep_mock.assert_not_called()

    def test_live_turn_pacer_waits_for_minimum_gap(self) -> None:
        previous = s3.core._LAST_LIVE_TURN_FINISHED_AT
        try:
            s3.core._LAST_LIVE_TURN_FINISHED_AT = 100.0
            with (
                patch.object(
                    s3.core.time,
                    "monotonic",
                    return_value=110.0,
                ),
                patch.object(
                    s3.core.time,
                    "sleep",
                ) as sleep_mock,
            ):
                s3.core._pace_before_live_turn(
                    gap_seconds=30,
                )

            sleep_mock.assert_called_once_with(20.0)
        finally:
            s3.core._LAST_LIVE_TURN_FINISHED_AT = previous

    def test_live_turn_pacer_skips_when_gap_already_elapsed(self) -> None:
        previous = s3.core._LAST_LIVE_TURN_FINISHED_AT
        try:
            s3.core._LAST_LIVE_TURN_FINISHED_AT = 100.0
            with (
                patch.object(
                    s3.core.time,
                    "monotonic",
                    return_value=140.0,
                ),
                patch.object(
                    s3.core.time,
                    "sleep",
                ) as sleep_mock,
            ):
                s3.core._pace_before_live_turn(
                    gap_seconds=30,
                )

            sleep_mock.assert_not_called()
        finally:
            s3.core._LAST_LIVE_TURN_FINISHED_AT = previous


    def test_recent_rate_limit_wait_happens_before_target_reset(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            private_root = Path(raw) / "private"
            acceptance_root = Path(raw) / "acceptance"
            events = []

            with (
                patch.object(s3.core, "_preflight_repo"),
                patch.object(s3, "_candidate_commit", return_value="d" * 40),
                patch.object(s3.core, "_configure_uwa_route"),
                patch.object(s3.core, "_start_standalone_listener"),
                patch.object(s3.core, "_health_ready", return_value={}),
                patch.object(
                    s3.core,
                    "_validation_python",
                    return_value=sys.executable,
                ),
                patch.object(
                    s3,
                    "_wait_for_recent_rate_limit_window",
                    side_effect=lambda *_args, **_kwargs: events.append("wait"),
                ),
                patch.object(
                    s3,
                    "_quiet_codex_desktop",
                    return_value=False,
                ),
                patch.object(s3.core, "_wait_request_cleanup"),
                patch.object(
                    s3,
                    "_reset_acceptance_chatgpt_target",
                    side_effect=lambda *_args, **_kwargs: (
                        events.append("reset") or {}
                    ),
                ),
                patch.object(
                    s3,
                    "_run_surface_preflight",
                    return_value={
                        "ok": True,
                        "actions": [],
                    },
                ),
                patch.object(s3.core, "_restart_standalone_listener"),
                patch.object(
                    s3,
                    "_passive_surface_recheck",
                    return_value={"blocking_reason": "none"},
                ),
                patch.object(s3.core, "run", return_value=0),
                patch.object(s3, "_promote_core_result"),
                patch.object(s3, "_restore_codex_desktop"),
            ):
                rc = s3.run(
                    acceptance_root=acceptance_root,
                    private_root=private_root,
                    turn_timeout_sec=60,
                    compaction_timeout_sec=60,
                )

            self.assertEqual(rc, 0)
            self.assertEqual(events[:2], ["wait", "reset"])


    def test_repeated_rate_limits_use_exponential_cross_run_backoff(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            private_root = Path(raw)

            with patch.object(s3.time, "time", return_value=1000.0):
                s3._record_rate_limit_marker(private_root)

            first = json.loads(
                s3._rate_limit_marker_path(private_root).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(first["streak"], 1)

            with patch.object(s3.time, "time", return_value=1100.0):
                s3._record_rate_limit_marker(private_root)

            second = json.loads(
                s3._rate_limit_marker_path(private_root).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(second["streak"], 2)

            with patch.object(s3.time, "time", return_value=1100.0):
                remaining = s3._recent_rate_limit_remaining_seconds(
                    private_root
                )

            self.assertEqual(remaining, 360.0)

    def test_old_rate_limit_marker_resets_streak(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            private_root = Path(raw)

            with patch.object(s3.time, "time", return_value=1000.0):
                s3._record_rate_limit_marker(private_root)

            with patch.object(s3.time, "time", return_value=5000.0):
                s3._record_rate_limit_marker(private_root)

            payload = json.loads(
                s3._rate_limit_marker_path(private_root).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(payload["streak"], 1)

    def test_recent_rate_limit_raises_recovery_turn_gap(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            private_root = Path(raw)

            with patch.object(s3.time, "time", return_value=1000.0):
                s3._record_rate_limit_marker(private_root)

            old = os.environ.get(
                "UWA_S3_MIN_LIVE_TURN_GAP_SEC"
            )
            old_recovery = os.environ.get(
                "UWA_S3_RATE_LIMIT_RECOVERY_TURN_GAP_SEC"
            )
            try:
                os.environ["UWA_S3_MIN_LIVE_TURN_GAP_SEC"] = "30"
                os.environ[
                    "UWA_S3_RATE_LIMIT_RECOVERY_TURN_GAP_SEC"
                ] = "60"

                s3._apply_rate_limit_recovery_pacing(
                    private_root
                )

                self.assertEqual(
                    os.environ["UWA_S3_MIN_LIVE_TURN_GAP_SEC"],
                    "60",
                )
            finally:
                if old is None:
                    os.environ.pop(
                        "UWA_S3_MIN_LIVE_TURN_GAP_SEC",
                        None,
                    )
                else:
                    os.environ[
                        "UWA_S3_MIN_LIVE_TURN_GAP_SEC"
                    ] = old

                if old_recovery is None:
                    os.environ.pop(
                        "UWA_S3_RATE_LIMIT_RECOVERY_TURN_GAP_SEC",
                        None,
                    )
                else:
                    os.environ[
                        "UWA_S3_RATE_LIMIT_RECOVERY_TURN_GAP_SEC"
                    ] = old_recovery


if __name__ == "__main__":
    unittest.main()
