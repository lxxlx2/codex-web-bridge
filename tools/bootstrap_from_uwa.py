#!/usr/bin/env python3
"""Bootstrap the standalone development tree from the validated UWA baseline.

This script intentionally operates only on the standalone repository's
`standalone-dev` branch. It clones the validated integration repository into a
private temporary directory, computes a conservative local-import closure from
Codex bridge entry points using only the Python stdlib, adds known import-time
side-effect modules plus release-validation files, and copies that candidate set
into this repository.

The bootstrap is deliberately conservative: S2 will remove generic UWA runtime
only after standalone import/CI/live parity proves it unnecessary.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path
from typing import Iterable

TARGET = Path(__file__).resolve().parents[1]
SOURCE_REPO = "https://github.com/lxxlx2/universal-web-api.git"
SOURCE_COMMIT = "a140002e65a02a3323abcde3e1fdb8674710c996"
EXPECTED_BRANCH = "standalone-dev"

SEEDS = [
    "app/api/codex_compact.py",
    "app/api/codex_compat.py",
    "app/api/codex_responses.py",
    "app/api/codex_responses_v2.py",
    "app/core/workflow/executor_send.py",
    "app/services/chatgpt_web_mode.py",
    "app/services/chatgpt_web_prepare.py",
    "app/services/client_tool_policy.py",
    "app/services/codex_metadata_helper.py",
    "app/services/codex_network_tuning.py",
    "app/services/codex_remote_compaction_v2.py",
    "app/services/codex_required_tool_language_patch.py",
    "app/services/codex_responses_state.py",
    "app/services/codex_stream_compat.py",
    "app/services/codex_v2_runtime_hardening.py",
    "app/services/codex_web_policy.py",
    "app/services/codex_web_session_affinity.py",
    "app/services/codex_wire_observability.py",
    "app/services/codex_workspace_refusal_language_patch.py",
    "app/services/tool_calling.py",
    "tools/codex_provider_switch.py",
    "tools/codex_uwa_lifecycle.py",
    "tools/codex_uwa_memory_guard.py",
    "tools/install_codex_uwa_commands.py",
    "tools/public_repo_safety_check.py",
]

IMPORT_SIDE_EFFECT_FILES = [
    "app/core/browser/__init__.py",
    "app/core/config_parts/cute_translator.py",
    "app/core/config_parts/exceptions.py",
    "app/core/config_parts/log_formatters.py",
    "app/core/config_parts/log_redaction.py",
    "app/core/config_parts/message_validator.py",
    "app/core/config_parts/secure_logger.py",
    "app/core/config_parts/sse_formatter.py",
    "app/core/page_capture/base.py",
    "app/core/page_capture/registry.py",
    "app/core/page_capture/request_transport.py",
    "app/core/parsers/aistudio_parser.py",
    "app/core/parsers/chatgpt_parser.py",
    "app/core/parsers/claude_parser.py",
    "app/core/parsers/deepseek_parser.py",
    "app/core/parsers/doubao_parser.py",
    "app/core/parsers/gemini_parser.py",
    "app/core/parsers/glm_parser.py",
    "app/core/parsers/grok_parser.py",
    "app/core/parsers/kimi_parser.py",
    "app/core/parsers/lmarena_battle_side_parser.py",
    "app/core/parsers/lmarena_image_side_left_parser.py",
    "app/core/parsers/lmarena_image_side_right_parser.py",
    "app/core/parsers/lmarena_side_left_parser.py",
    "app/core/parsers/mimo_parser.py",
    "app/core/parsers/mimo_runtime_parser.py",
    "app/core/parsers/qwen_parser.py",
    "app/core/parsers/registry.py",
    "app/core/tab_pool_parts/__init__.py",
    "app/models/__init__.py",
    "app/utils/__init__.py",
    "app/utils/paste.py",
]

CONFIG_FILES = [
    "config/browser_config.json",
    "config/commands.json",
    "config/extractors.json",
    "config/image_presets.json",
    "config/marketplace_cache.json",
    "config/parsers.json",
    "config/site_rules.json",
    "config/sites.json",
]

ROOT_FILES = ["requirements.txt", "LICENSE"]

PROTECTED_TARGET_FILES = {
    "README.md",
    "README.zh-CN.md",
    "NOTICE.md",
    "SECURITY.md",
    ".gitignore",
    ".env.example",
    "tools/bootstrap_from_uwa.py",
}

SKIP_PARTS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
}


def run(args: list[str], *, cwd: Path = TARGET, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def require_ok(result: subprocess.CompletedProcess[str], code: str) -> str:
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-8:]
        if tail:
            print(f"{code}_DETAIL=" + " | ".join(tail))
        raise SystemExit(code)
    return result.stdout.strip()


def git(*args: str) -> str:
    return require_ok(run(["git", *args], timeout=60), "BOOTSTRAP_GIT_FAILED")


def require_target_state() -> None:
    branch = git("branch", "--show-current")
    dirty = git("status", "--porcelain", "--untracked-files=all")
    remote = git("remote", "get-url", "origin")
    print(f"TARGET_BRANCH={branch}")
    print("TARGET_CLEAN=" + ("YES" if not dirty else "NO"))
    print("TARGET_REPOSITORY_MATCH=" + ("YES" if "codex-web-bridge" in remote else "NO"))
    if branch != EXPECTED_BRANCH:
        raise SystemExit("BOOTSTRAP_WRONG_BRANCH")
    if dirty:
        raise SystemExit("BOOTSTRAP_DIRTY_TARGET")
    if "codex-web-bridge" not in remote:
        raise SystemExit("BOOTSTRAP_WRONG_TARGET_REPOSITORY")


def python_files(root: Path) -> list[Path]:
    result: list[Path] = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if any(part in SKIP_PARTS for part in rel.parts):
            continue
        if path.is_file():
            result.append(path)
    return sorted(result)


def module_name(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def build_module_index(root: Path, files: Iterable[Path]) -> tuple[dict[str, Path], dict[Path, str]]:
    by_module: dict[str, Path] = {}
    by_path: dict[Path, str] = {}
    for path in files:
        mod = module_name(root, path)
        if mod:
            by_module[mod] = path
            by_path[path] = mod
    return by_module, by_path


def imported_names(tree: ast.AST, current_module: str) -> set[str]:
    names: set[str] = set()
    package = current_module.split(".")[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            keep = max(0, len(package) - node.level + 1)
            prefix = package[:keep]
            if node.module:
                prefix += node.module.split(".")
            base = ".".join(prefix)
        else:
            base = node.module or ""
        if base:
            names.add(base)
        for alias in node.names:
            if alias.name == "*":
                continue
            names.add(f"{base}.{alias.name}" if base else alias.name)
    return names


def resolve_local(name: str, by_module: dict[str, Path]) -> Path | None:
    current = name
    while current:
        if current in by_module:
            return by_module[current]
        if "." not in current:
            break
        current = current.rsplit(".", 1)[0]
    return None


def static_closure(source: Path) -> set[Path]:
    files = python_files(source)
    by_module, by_path = build_module_index(source, files)
    graph: dict[Path, set[Path]] = {path: set() for path in files}
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        current = by_path.get(path, "")
        for name in imported_names(tree, current):
            local = resolve_local(name, by_module)
            if local is not None and local != path:
                graph[path].add(local)

    queue: deque[Path] = deque()
    for rel in SEEDS:
        path = source / rel
        if not path.is_file():
            raise SystemExit(f"BOOTSTRAP_MISSING_SEED:{rel}")
        queue.append(path)

    seen: set[Path] = set()
    while queue:
        path = queue.popleft()
        if path in seen:
            continue
        seen.add(path)
        queue.extend(sorted(graph.get(path, set()) - seen))
    return seen


def validation_files(source: Path) -> set[Path]:
    tests = source / "tests"
    result: set[Path] = set()
    if not tests.is_dir():
        return result
    for path in tests.glob("test_codex_*.py"):
        if path.is_file():
            result.add(path)
    for path in tests.glob("test_chatgpt_web_*.py"):
        if path.is_file():
            result.add(path)
    for path in tests.glob("test_client_tool_policy*.py"):
        if path.is_file():
            result.add(path)
    for name in ["test_install_codex_uwa_commands.py", "test_security_hardening.py"]:
        path = tests / name
        if path.is_file():
            result.add(path)
    return result


def s3_operator_tools(source: Path) -> set[Path]:
    wanted = {
        "codex_auto_compact_trigger_probe.py",
        "codex_desktop_acceptance.py",
        "codex_large_context_acceptance.py",
        "codex_large_context_live.py",
        "codex_remote_compaction_trigger_probe.py",
        "codex_route_audit.py",
    }
    result: set[Path] = set()
    for name in wanted:
        path = source / "tools" / name
        if path.is_file():
            result.add(path)
    return result


def source_checkout(work: Path) -> Path:
    source = work / "source"
    require_ok(
        run(["git", "clone", "--filter=blob:none", "--no-checkout", SOURCE_REPO, str(source)], cwd=work, timeout=300),
        "BOOTSTRAP_SOURCE_CLONE_FAILED",
    )
    require_ok(
        run(["git", "checkout", "--detach", SOURCE_COMMIT], cwd=source, timeout=180),
        "BOOTSTRAP_SOURCE_CHECKOUT_FAILED",
    )
    actual = require_ok(run(["git", "rev-parse", "HEAD"], cwd=source, timeout=30), "BOOTSTRAP_SOURCE_HEAD_FAILED")
    print("SOURCE_BASELINE_MATCH=" + ("YES" if actual == SOURCE_COMMIT else "NO"))
    if actual != SOURCE_COMMIT:
        raise SystemExit("BOOTSTRAP_SOURCE_BASELINE_MISMATCH")
    return source


def add_existing(source: Path, relative_paths: Iterable[str], keep: set[Path]) -> None:
    for rel in relative_paths:
        path = source / rel
        if path.is_file():
            keep.add(path)


def add_tree_if_present(source: Path, rel: str, keep: set[Path]) -> None:
    root = source / rel
    if not root.is_dir():
        return
    for path in root.rglob("*"):
        if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts:
            keep.add(path)


def copy_candidate(source: Path) -> list[str]:
    keep = static_closure(source)
    add_existing(source, IMPORT_SIDE_EFFECT_FILES, keep)
    add_existing(source, CONFIG_FILES, keep)
    add_existing(source, ROOT_FILES, keep)
    keep.update(validation_files(source))
    keep.update(s3_operator_tools(source))
    add_tree_if_present(source, "scripts", keep)

    copied: list[str] = []
    for src in sorted(keep):
        rel = src.relative_to(source).as_posix()
        if rel in PROTECTED_TARGET_FILES:
            continue
        dst = TARGET / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel)

    manifest_dir = TARGET / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": 1,
        "source_repository": "lxxlx2/universal-web-api",
        "source_commit": SOURCE_COMMIT,
        "development_branch": EXPECTED_BRANCH,
        "candidate_file_count": len(copied),
        "candidate_files": copied,
        "status": "conservative_s2_input",
        "note": "Files are copied conservatively and are not the final standalone keep-set.",
    }
    (manifest_dir / "bootstrap-candidate.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (TARGET / "SOURCE_BASELINE").write_text(
        f"lxxlx2/universal-web-api@{SOURCE_COMMIT}\n",
        encoding="utf-8",
    )
    return copied


def validate_tree(copied: list[str]) -> None:
    py_files = [str(TARGET / rel) for rel in copied if rel.endswith(".py")]
    if py_files:
        result = run([sys.executable, "-m", "py_compile", *py_files], timeout=300)
        print(f"BOOTSTRAP_PY_COMPILE_RC={result.returncode}")
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()[-8:]
            if detail:
                print("BOOTSTRAP_PY_COMPILE_DETAIL=" + " | ".join(detail))
            raise SystemExit("BOOTSTRAP_PY_COMPILE_FAILED")
    diff = run(["git", "diff", "--check"], timeout=60)
    print(f"BOOTSTRAP_GIT_DIFF_CHECK_RC={diff.returncode}")
    if diff.returncode != 0:
        raise SystemExit("BOOTSTRAP_GIT_DIFF_CHECK_FAILED")


def commit_and_push() -> None:
    require_ok(run(["git", "add", "-A"], timeout=60), "BOOTSTRAP_GIT_ADD_FAILED")
    staged = require_ok(run(["git", "diff", "--cached", "--name-only"], timeout=60), "BOOTSTRAP_GIT_STAGE_READ_FAILED")
    if not staged:
        print("BOOTSTRAP_COMMIT=SKIPPED_NO_CHANGES")
        return
    require_ok(
        run(["git", "commit", "-m", "Bootstrap conservative standalone candidate"], timeout=120),
        "BOOTSTRAP_GIT_COMMIT_FAILED",
    )
    require_ok(
        run(["git", "push", "origin", EXPECTED_BRANCH], timeout=180),
        "BOOTSTRAP_GIT_PUSH_FAILED",
    )
    print("BOOTSTRAP_COMMIT_PUSH=PASS")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--push", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.push and not args.commit:
        raise SystemExit("BOOTSTRAP_PUSH_REQUIRES_COMMIT")
    print("STANDALONE_BOOTSTRAP_BEGIN")
    require_target_state()
    with tempfile.TemporaryDirectory(prefix="codex-web-bridge-bootstrap-") as raw:
        work = Path(raw)
        source = source_checkout(work)
        copied = copy_candidate(source)
    print(f"BOOTSTRAP_CANDIDATE_FILE_COUNT={len(copied)}")
    validate_tree(copied)
    print("BOOTSTRAP_TREE=PASS")
    if args.commit:
        commit_and_push()
    print("STANDALONE_BOOTSTRAP=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
