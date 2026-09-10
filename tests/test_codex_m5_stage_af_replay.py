from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "codex_m5_final_regression_safe_v2.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("codex_m5_final_regression_safe_v2_test", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load M5 safe v2 runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class M5StageAFReplayTests(unittest.TestCase):
    def test_fresh_replay_root_does_not_preexist_and_full_replay_passes(self):
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "replay"
            original_parent = module.PRIVATE_REPLAY_PARENT
            module.PRIVATE_REPLAY_PARENT = parent
            try:
                root = module._fresh_replay_root()
                self.assertFalse(root.exists())

                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    module.run_stage_a_f_replay(sys.executable)

                text = output.getvalue()
                self.assertIn("M5_STAGE_A_F_REPLAY_SETUP_RC=0", text)
                self.assertIn("M5_STAGE_A_F_REPLAY_OWNERSHIP_MARKER=YES", text)
                self.assertIn("M5_STAGE_A_F_AGGREGATE=PASS", text)
                self.assertIn("M5_STAGE_A_F_REPLAY_CLEANED=YES", text)
                self.assertFalse(any(parent.iterdir()))
            finally:
                module.PRIVATE_REPLAY_PARENT = original_parent


if __name__ == "__main__":
    unittest.main()
