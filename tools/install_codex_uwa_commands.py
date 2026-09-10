#!/usr/bin/env python3
"""Install thin ~/bin wrappers for the versioned Codex/UWA lifecycle tools.

The wrappers intentionally contain almost no lifecycle or provider-switch logic.
Pulling a new repository revision therefore updates behavior without leaving
stale copies in ``~/bin``.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BIN_DIR = Path.home() / "bin"

STOP_WRAPPER = '''#!/bin/zsh
set -euo pipefail
ROOT="${CODEX_UWA_ROOT:-$HOME/universal-web-api}"
exec python3 "$ROOT/tools/codex_uwa_lifecycle.py" stop --root "$ROOT"
'''

START_WRAPPER = '''#!/bin/zsh
set -euo pipefail
ROOT="${CODEX_UWA_ROOT:-$HOME/universal-web-api}"
STATE="$HOME/.uwa"

python3 "$ROOT/tools/codex_uwa_memory_guard.py" disable
python3 "$ROOT/tools/codex_provider_switch.py" uwa

osascript -e 'tell application "Codex" to quit' >/dev/null 2>&1 || true
sleep 1

python3 "$ROOT/tools/codex_uwa_lifecycle.py" restart --root "$ROOT"

if curl -fsS 'http://127.0.0.1:8199/v1/models?client_version=0.153.4' 2>/dev/null \
    | python3 -c '
import json,sys
try:
    d=json.load(sys.stdin)
    models=d.get("models", [])
    assert any(m.get("slug")=="chatgpt" for m in models)
except Exception:
    raise SystemExit(1)
' >/dev/null 2>&1
then
    echo "Codex 模型目录兼容检查通过"
else
    echo "警告：Codex 模型目录兼容检查未通过"
fi

open -a Codex

echo "Codex Desktop 已用 UWA 配置启动"
echo "UWA 日志：$STATE/uwa.log"
echo "健康检查：http://127.0.0.1:8199/health"
'''


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.chmod(0o755)
    os.replace(tmp, path)
    path.chmod(0o755)


def install(bin_dir: Path = DEFAULT_BIN_DIR) -> tuple[Path, Path]:
    bin_dir = bin_dir.expanduser()
    start = bin_dir / "codex-uwa"
    stop = bin_dir / "codex-uwa-stop"
    _write_executable(start, START_WRAPPER)
    _write_executable(stop, STOP_WRAPPER)
    return start, stop


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bin-dir", type=Path, default=DEFAULT_BIN_DIR)
    args = parser.parse_args()

    start, stop = install(args.bin_dir)
    print(f"INSTALLED={start}")
    print(f"INSTALLED={stop}")
    print(f"REPO_ROOT={REPO_ROOT}")
    print("WRAPPER_MODE=VERSIONED_REPO_LOGIC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
