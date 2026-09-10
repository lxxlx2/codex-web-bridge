#!/usr/bin/env python3
"""Deterministic static/runtime dependency audit for the standalone bridge.

The audit is intentionally conservative.  It computes a local Python import
closure from the standalone application/runtime entrypoints, records modules
loaded by importing ``main`` in a clean process, and reports modules outside the
static closure as pruning candidates.  It never deletes files.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import json
import sys
from collections import deque
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SEED_MODULES = (
    "main",
    "app.api.standalone_routes",
    "app.api.codex_runtime",
    "app.api.codex_compact",
    "app.api.codex_responses",
    "app.api.codex_responses_v2",
    "app.services.codex_chatgpt_executor",
)
STARTUP_FORBIDDEN = (
    "app.api.anthropic_routes",
    "app.api.browser_routes",
    "app.api.cmd_routes",
    "app.api.config_routes",
    "app.api.provider",
    "app.api.routes",
    "app.api.system",
    "app.api.tab_routes",
    "app.api.legacy_chat_runtime",
)
EXPECTED_STARTUP = (
    "main",
    "app.api.standalone_routes",
    "app.api.codex_runtime",
    "app.services.codex_chatgpt_executor",
)


def _runtime_python_paths() -> list[Path]:
    paths = [ROOT / "main.py", ROOT / "start.py", ROOT / "security_guard.py"]
    paths.extend(sorted((ROOT / "app").rglob("*.py")))
    return [path for path in paths if path.is_file()]


def _module_name(path: Path) -> str:
    relative = path.relative_to(ROOT)
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = Path(parts[-1]).stem
    return ".".join(parts)


def _module_index() -> dict[str, Path]:
    return {_module_name(path): path for path in _runtime_python_paths()}


def _package_for(module: str, path: Path) -> str:
    if path.name == "__init__.py":
        return module
    return module.rpartition(".")[0]


def _relative_base(module: str, path: Path, level: int, imported: str | None) -> str:
    package = _package_for(module, path)
    parts = package.split(".") if package else []
    if level > 0:
        trim = level - 1
        if trim:
            parts = parts[:-trim] if trim <= len(parts) else []
    if imported:
        parts.extend(imported.split("."))
    return ".".join(part for part in parts if part)


def _literal_import_target(call: ast.Call) -> str | None:
    name = ""
    if isinstance(call.func, ast.Name):
        name = call.func.id
    elif isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name):
        name = f"{call.func.value.id}.{call.func.attr}"
    if name not in {"__import__", "importlib.import_module"} or not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        value = first.value.strip()
        if value and not value.startswith("."):
            return value
    return None


def _best_local_target(name: str, index: dict[str, Path]) -> str | None:
    candidate = name
    while candidate:
        if candidate in index:
            return candidate
        candidate = candidate.rpartition(".")[0]
    return None


def _imports_for(module: str, path: Path, index: dict[str, Path]) -> tuple[set[str], set[str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"cannot parse {path.relative_to(ROOT)}: {exc}") from exc

    local: set[str] = set()
    external: set[str] = set()

    def add_target(target: str) -> None:
        target = target.strip()
        if not target:
            return
        matched = _best_local_target(target, index)
        if matched:
            local.add(matched)
        else:
            external.add(target.split(".", 1)[0])

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add_target(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = _relative_base(module, path, node.level, node.module)
            else:
                base = node.module or ""
            if base:
                add_target(base)
            for alias in node.names:
                if alias.name == "*":
                    continue
                child = f"{base}.{alias.name}" if base else alias.name
                if child in index:
                    local.add(child)
        elif isinstance(node, ast.Call):
            target = _literal_import_target(node)
            if target:
                add_target(target)

    return local, external


def _static_closure(index: dict[str, Path]) -> tuple[set[str], set[str], dict[str, list[str]]]:
    missing = sorted(seed for seed in SEED_MODULES if seed not in index)
    if missing:
        raise RuntimeError("missing audit seed modules: " + ", ".join(missing))

    closure: set[str] = set()
    external_roots: set[str] = set()
    edges: dict[str, list[str]] = {}
    queue: deque[str] = deque(SEED_MODULES)

    while queue:
        module = queue.popleft()
        if module in closure:
            continue
        closure.add(module)
        local, external = _imports_for(module, index[module], index)
        local = {item for item in local if item in index}
        edges[module] = sorted(local)
        external_roots.update(external)
        for dependency in sorted(local):
            if dependency not in closure:
                queue.append(dependency)

    return closure, external_roots, edges


def _startup_modules(index: dict[str, Path]) -> set[str]:
    importlib.import_module("main")
    return {name for name in sys.modules if name in index}


def _stdlib_filtered(values: Iterable[str]) -> list[str]:
    stdlib = getattr(sys, "stdlib_module_names", set())
    return sorted(value for value in set(values) if value and value not in stdlib)


def build_report() -> dict[str, object]:
    index = _module_index()
    closure, external_roots, edges = _static_closure(index)
    startup = _startup_modules(index)
    unreachable = sorted(set(index) - closure)
    forbidden_loaded = sorted(set(STARTUP_FORBIDDEN) & startup)
    expected_missing = sorted(set(EXPECTED_STARTUP) - startup)

    obvious_generic_candidates = sorted(
        module
        for module in unreachable
        if module.startswith(
            (
                "app.api.anthropic_",
                "app.api.browser_",
                "app.api.cmd_",
                "app.api.config_",
                "app.api.provider",
                "app.api.routes",
                "app.api.system",
                "app.api.tab_",
                "app.services.arena_",
                "app.services.catalog_",
                "app.services.command_",
                "app.services.config",
            )
        )
    )
    non_chatgpt_parser_candidates = sorted(
        module
        for module in unreachable
        if module.startswith("app.core.parsers.")
        and module not in {
            "app.core.parsers.base",
            "app.core.parsers.chatgpt_parser",
            "app.core.parsers.registry",
        }
    )

    return {
        "schema_version": 1,
        "seed_modules": list(SEED_MODULES),
        "runtime_python_module_count": len(index),
        "static_closure_count": len(closure),
        "startup_loaded_local_count": len(startup),
        "unreachable_candidate_count": len(unreachable),
        "static_closure": sorted(closure),
        "startup_loaded_local": sorted(startup),
        "external_import_roots_nonstdlib": _stdlib_filtered(external_roots),
        "startup_forbidden_loaded": forbidden_loaded,
        "expected_startup_missing": expected_missing,
        "obvious_generic_candidates": obvious_generic_candidates,
        "non_chatgpt_parser_candidates": non_chatgpt_parser_candidates,
        "unreachable_candidates": unreachable,
        "static_edges": edges,
    }


def _print_summary(report: dict[str, object]) -> None:
    print(f"RUNTIME_PYTHON_MODULE_COUNT={report['runtime_python_module_count']}")
    print(f"STATIC_CLOSURE_COUNT={report['static_closure_count']}")
    print(f"STARTUP_LOADED_LOCAL_COUNT={report['startup_loaded_local_count']}")
    print(f"UNREACHABLE_CANDIDATE_COUNT={report['unreachable_candidate_count']}")
    print(
        "STARTUP_FORBIDDEN_LOADED="
        + (",".join(report["startup_forbidden_loaded"]) or "NONE")
    )
    print(
        "EXPECTED_STARTUP_MISSING="
        + (",".join(report["expected_startup_missing"]) or "NONE")
    )
    print(
        "EXTERNAL_IMPORT_ROOTS_NONSTDLIB="
        + (",".join(report["external_import_roots_nonstdlib"]) or "NONE")
    )
    print(
        "OBVIOUS_GENERIC_CANDIDATE_COUNT="
        + str(len(report["obvious_generic_candidates"]))
    )
    print(
        "NON_CHATGPT_PARSER_CANDIDATE_COUNT="
        + str(len(report["non_chatgpt_parser_candidates"]))
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--print-candidates", action="store_true")
    args = parser.parse_args()

    try:
        report = build_report()
    except Exception as exc:
        print(f"STANDALONE_DEPENDENCY_AUDIT=FAIL")
        print(f"ERROR={exc}")
        return 1

    _print_summary(report)
    if args.print_candidates:
        for module in report["obvious_generic_candidates"]:
            print(f"GENERIC_CANDIDATE={module}")
        for module in report["non_chatgpt_parser_candidates"]:
            print(f"PARSER_CANDIDATE={module}")

    if args.json_out is not None:
        output = args.json_out
        if not output.is_absolute():
            output = ROOT / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"AUDIT_JSON_WRITTEN={output.relative_to(ROOT) if output.is_relative_to(ROOT) else output.name}")

    if args.check:
        if report["startup_forbidden_loaded"] or report["expected_startup_missing"]:
            print("STANDALONE_DEPENDENCY_AUDIT=FAIL")
            return 1

    print("STANDALONE_DEPENDENCY_AUDIT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
