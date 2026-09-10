from __future__ import annotations

import importlib
import sys
import unittest


class StandaloneApiImportBoundaryTests(unittest.TestCase):
    def test_api_package_import_does_not_eager_load_generic_routes(self) -> None:
        generic = {
            "app.api.anthropic_routes",
            "app.api.browser_routes",
            "app.api.cmd_routes",
            "app.api.config_routes",
            "app.api.provider",
            "app.api.system",
            "app.api.tab_routes",
        }
        importlib.import_module("app.api")
        loaded = sorted(generic.intersection(sys.modules))
        self.assertEqual(loaded, [])


if __name__ == "__main__":
    unittest.main()
