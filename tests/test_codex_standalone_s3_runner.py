from __future__ import annotations

import json
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


if __name__ == "__main__":
    unittest.main()
