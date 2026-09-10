#!/usr/bin/env python3
"""Install thin user-facing wrappers for Codex Web Bridge.

The wrappers keep lifecycle/provider logic in the checked-out repository. They
pin the repository path at install time so the standalone project works from any
clone location instead of assuming ``~/universal-web-api``.
"""

from __future__ import annotations

import argparse
import os
import shlex
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BIN_DIR = Path.home() / "bin"


def _root_line(repo_root: Path = REPO_ROOT) -> str:
    return f"ROOT={shlex.quote(str(repo_root.resolve()))}"


def _start_wrapper(repo_root: Path = REPO_ROOT) -> str:
    return f'''#!/bin/zsh
set -euo pipefail
{_root_line(repo_root)}
STATE="$HOME/.uwa"

python3 "$ROOT/tools/codex_uwa_memory_guard.py" disable
python3 "$ROOT/tools/codex_provider_switch.py" uwa

osascript -e 'tell application "Codex" to quit' >/dev/null 2>&1 || true
sleep 1

python3 "$ROOT/tools/codex_uwa_lifecycle.py" restart --root "$ROOT"

if curl -fsS 'http://127.0.0.1:8199/v1/models?client_version=0.153.4' 2>/dev/null \\
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
    echo "Codex model catalog compatibility check passed"
else
    echo "Warning: Codex model catalog compatibility check did not pass"
fi

open -a Codex

echo "Codex Desktop started with the Web Bridge route"
echo "Bridge log: $STATE/uwa.log"
echo "Health: http://127.0.0.1:8199/health"
'''


def _stop_wrapper(repo_root: Path = REPO_ROOT) -> str:
    return f'''#!/bin/zsh
set -euo pipefail
{_root_line(repo_root)}
exec python3 "$ROOT/tools/codex_uwa_lifecycle.py" stop --root "$ROOT"
'''


def _official_wrapper(repo_root: Path = REPO_ROOT) -> str:
    return f'''#!/bin/zsh
set -euo pipefail
{_root_line(repo_root)}
exec python3 "$ROOT/tools/codex_provider_switch.py" official
'''


def _status_wrapper(repo_root: Path = REPO_ROOT) -> str:
    return f'''#!/bin/zsh
set -euo pipefail
{_root_line(repo_root)}
python3 "$ROOT/tools/codex_provider_switch.py" status
python3 "$ROOT/tools/codex_uwa_lifecycle.py" status --root "$ROOT"
'''


START_WRAPPER = _start_wrapper()
STOP_WRAPPER = _stop_wrapper()
OFFICIAL_WRAPPER = _official_wrapper()
STATUS_WRAPPER = _status_wrapper()


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
    official = bin_dir / "codex-official"
    status = bin_dir / "codex-uwa-status"
    _write_executable(start, START_WRAPPER)
    _write_executable(stop, STOP_WRAPPER)
    _write_executable(official, OFFICIAL_WRAPPER)
    _write_executable(status, STATUS_WRAPPER)
    return start, stop


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bin-dir", type=Path, default=DEFAULT_BIN_DIR)
    args = parser.parse_args()

    start, stop = install(args.bin_dir)
    bin_dir = args.bin_dir.expanduser()
    print(f"INSTALLED={start}")
    print(f"INSTALLED={stop}")
    print(f"INSTALLED={bin_dir / 'codex-official'}")
    print(f"INSTALLED={bin_dir / 'codex-uwa-status'}")
    print(f"REPO_ROOT={REPO_ROOT}")
    print("WRAPPER_MODE=VERSIONED_REPO_LOGIC")
    if str(bin_dir) not in os.environ.get("PATH", "").split(os.pathsep):
        print(f"PATH_HINT=export PATH={bin_dir}:$PATH")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
