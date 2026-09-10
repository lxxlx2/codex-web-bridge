from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE_CAPTURE = ROOT / "app" / "core" / "page_capture"


class StandalonePageCaptureBoundaryTests(unittest.TestCase):
    def test_removed_provider_specific_modules_are_absent(self) -> None:
        self.assertFalse((PAGE_CAPTURE / "kimi_fetch_capture.py").exists())
        self.assertFalse((PAGE_CAPTURE / "deepseek_request_transport.py").exists())

    def test_package_does_not_reference_removed_provider_modules(self) -> None:
        source = (PAGE_CAPTURE / "__init__.py").read_text(encoding="utf-8")

        self.assertNotIn("kimi_fetch_capture", source)
        self.assertNotIn("deepseek_request_transport", source)

    def test_generic_page_capture_api_imports(self) -> None:
        from app.core.page_capture import (
            create_page_fetch_capture,
            get_page_request_transport_profile,
            get_page_request_transport_profiles,
        )

        self.assertIsNotNone(create_page_fetch_capture)
        self.assertIsNotNone(get_page_request_transport_profile)
        self.assertIsNotNone(get_page_request_transport_profiles)


if __name__ == "__main__":
    unittest.main()
