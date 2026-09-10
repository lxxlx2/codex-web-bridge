from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import standalone_s3_live_acceptance as s3


class StandaloneS3RunnerTests(unittest.TestCase):
    def test_cli_imports_without_running_live_gate(self) -> None:
        result = subprocess.run(
            [sys.executable, str(TOOLS / "standalone_s3_live_acceptance.py"), "--help"],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("One-shot standalone S3 CLI/live acceptance", result.stdout)

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

    def test_remote_normalization_recognizes_integrated_origin(self) -> None:
        self.assertEqual(
            s3._normalize_remote("git@github.com:lxxlx2/universal-web-api.git"),
            "https://github.com/lxxlx2/universal-web-api",
        )


if __name__ == "__main__":
    unittest.main()
