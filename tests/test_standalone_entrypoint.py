from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _imports(path: str) -> set[str]:
    tree = ast.parse(_source(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
    return imports


class StandaloneEntrypointTests(unittest.TestCase):
    def test_standalone_route_aggregate_is_codex_only(self) -> None:
        imports = _imports("app/api/standalone_routes.py")
        self.assertIn("app.api.codex_compat", imports)
        self.assertIn("app.api.codex_compact", imports)
        self.assertIn("app.api.codex_responses_v2", imports)
        for forbidden in {
            "app.api.anthropic_routes",
            "app.api.browser_routes",
            "app.api.cmd_routes",
            "app.api.config_routes",
            "app.api.provider",
            "app.api.system",
            "app.api.tab_routes",
            "app.api.routes",
        }:
            self.assertNotIn(forbidden, imports)

    def test_codex_model_catalog_no_longer_imports_generic_chat_api(self) -> None:
        imports = _imports("app/api/codex_compat.py")
        source = _source("app/api/codex_compat.py")
        self.assertNotIn("app.api.chat", imports)
        self.assertIn("app.api.deps", imports)
        self.assertIn('"id": "chatgpt"', source)
        self.assertIn("verify_service_auth", source)

    def test_parser_package_exports_only_chatgpt_runtime(self) -> None:
        source = _source("app/core/parsers/__init__.py")
        tree = ast.parse(source)
        direct_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertIn("chatgpt_parser", direct_modules)
        for forbidden in {
            "gemini_parser",
            "deepseek_parser",
            "aistudio_parser",
            "doubao_parser",
            "claude_parser",
            "kimi_parser",
            "glm_parser",
            "qwen_parser",
            "mimo_parser",
            "lmarena_parser",
            "grok_parser",
        }:
            self.assertNotIn(forbidden, direct_modules)
        self.assertNotIn("_LAZY_EXPORTS", source)
        self.assertNotIn("importlib", source)
        parser_config = json.loads(_source("config/parsers.json"))
        self.assertEqual(parser_config.get("parsers"), {})

    def test_main_uses_standalone_routes_and_minimal_health_surface(self) -> None:
        source = _source("main.py")
        self.assertIn("from app.api.standalone_routes import router as codex_router", source)
        self.assertIn('@app.get("/health")', source)
        self.assertIn('"running_count"', source)
        self.assertNotIn("app.api.routes", source)
        self.assertNotIn("StaticFiles", source)
        self.assertNotIn("schedule_startup_update_check", source)

    def test_launcher_bootstraps_local_venv_and_enforces_loopback(self) -> None:
        source = _source("start.py")
        self.assertIn('VENV_DIR = ROOT / ".venv"', source)
        self.assertIn('REQUIREMENTS = ROOT / "requirements.txt"', source)
        self.assertIn('"-m",\n        "uvicorn"', source)
        self.assertIn("_loopback_host", source)
        self.assertNotIn("start_upstream", source)
        self.assertNotIn("AUTO_UPDATE_ENABLED", source)

    def test_environment_template_matches_runtime_keys(self) -> None:
        lines = {
            line.split("=", 1)[0]
            for line in _source(".env.example").splitlines()
            if line.strip() and not line.lstrip().startswith("#") and "=" in line
        }
        self.assertIn("APP_HOST", lines)
        self.assertIn("APP_PORT", lines)
        self.assertIn("BROWSER_PORT", lines)
        self.assertIn("UWA_CODEX_WEB_MODE_ENABLED", lines)
        self.assertNotIn("HOST", lines)
        self.assertNotIn("PORT", lines)


if __name__ == "__main__":
    unittest.main()
