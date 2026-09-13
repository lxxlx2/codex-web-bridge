from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

import main


class _Browser:
    def __init__(self, connected: bool):
        self.connected = connected

    def health_check(self):
        return {
            "status": "healthy" if self.connected else "unhealthy",
            "connected": self.connected,
        }


class StandaloneHealthTests(unittest.TestCase):
    def test_chatgpt_status_merges_cooldown_and_sanitized_surface(self) -> None:
        surface = {
            "surface_kind": "work",
            "surface_ready": False,
            "blocking_reason": "work_surface",
        }
        with patch.object(
            main,
            "rate_limit_status",
            return_value={
                "cooldown_active": False,
                "cooldown_remaining_seconds": 0.0,
                "hits": 0,
            },
        ), patch.object(main, "sanitized_surface_status", return_value=surface):
            status = main._chatgpt_web_status()

        self.assertFalse(status["cooldown_active"])
        self.assertEqual(status["surface"], surface)

    def test_surface_block_does_not_mark_transport_unhealthy(self) -> None:
        blocked = {
            "cooldown_active": False,
            "cooldown_remaining_seconds": 0.0,
            "hits": 0,
            "surface": {
                "surface_kind": "work",
                "surface_ready": False,
                "blocking_reason": "work_surface",
            },
        }
        with patch.object(main, "get_browser", return_value=_Browser(True)), patch.object(
            main, "_request_status", return_value={"running_count": 0}
        ), patch.object(main, "_chatgpt_web_status", return_value=blocked):
            payload = asyncio.run(main.health())

        self.assertEqual(payload["service"], "healthy")
        self.assertFalse(payload["chatgpt_web"]["surface"]["surface_ready"])

    def test_browser_disconnect_marks_service_degraded(self) -> None:
        ready = {
            "cooldown_active": False,
            "cooldown_remaining_seconds": 0.0,
            "hits": 0,
            "surface": {
                "surface_kind": "unknown",
                "surface_ready": False,
                "blocking_reason": "target_missing",
            },
        }
        with patch.object(main, "get_browser", return_value=_Browser(False)), patch.object(
            main, "_request_status", return_value={"running_count": 0}
        ), patch.object(main, "_chatgpt_web_status", return_value=ready):
            payload = asyncio.run(main.health())

        self.assertEqual(payload["service"], "degraded")


if __name__ == "__main__":
    unittest.main()
