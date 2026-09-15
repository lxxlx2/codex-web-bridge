#!/usr/bin/env python3
"""Safely disable/restore Codex automatic memories while using the UWA web bridge.

Why this exists:
- Codex can launch background memory-consolidation work after a foreground task.
- With a custom provider, those auxiliary requests can also be routed through UWA,
  consuming the controlled ChatGPT tab and creating extra web conversations.
- The bridge currently treats Codex project/thread history, UWA continuation state,
  and Git checkpoints as the supported continuity layers. Automatic Codex memories
  are therefore disabled in UWA mode until they have their own live acceptance.

This tool never reads or writes memory contents. It only edits the [memories]
configuration booleans in ~/.codex/config.toml and stores the previous values in
~/.uwa so they can be restored later.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.11+ in supported environments
    tomllib = None

CONFIG_PATH = Path.home() / ".codex" / "config.toml"
STATE_DIR = Path.home() / ".uwa"
STATE_PATH = STATE_DIR / "codex_memories_guard.json"
SECTION = "memories"
KEYS = ("generate_memories", "use_memories")


def _chmod_private(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        pass


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists() or tomllib is None:
        return {}
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return data if isinstance(data, dict) else {}


def _current_values(path: Path) -> dict[str, Any]:
    memories = _read_toml(path).get(SECTION, {})
    if not isinstance(memories, dict):
        memories = {}
    return {key: memories.get(key, None) for key in KEYS}


def _replace_section_keys(text: str, values: dict[str, bool | None]) -> str:
    lines = text.splitlines()
    section_re = re.compile(r"^\s*\[([^]]+)\]\s*(?:#.*)?$")
    key_res = {key: re.compile(rf"^\s*{re.escape(key)}\s*=") for key in KEYS}

    section_start = None
    section_end = len(lines)
    for idx, line in enumerate(lines):
        match = section_re.match(line)
        if not match:
            continue
        name = match.group(1).strip()
        if name == SECTION:
            section_start = idx
            for j in range(idx + 1, len(lines)):
                if section_re.match(lines[j]):
                    section_end = j
                    break
            break

    if section_start is None:
        additions = []
        for key in KEYS:
            value = values.get(key, None)
            if value is not None:
                additions.append(f"{key} = {'true' if value else 'false'}")
        if not additions:
            return text
        base = text.rstrip()
        block = "\n".join([f"[{SECTION}]", *additions])
        return f"{base}\n\n{block}\n" if base else f"{block}\n"

    body = lines[section_start + 1 : section_end]
    seen: set[str] = set()
    new_body: list[str] = []
    for line in body:
        replaced = False
        for key, pattern in key_res.items():
            if pattern.match(line):
                seen.add(key)
                value = values.get(key, None)
                if value is not None:
                    new_body.append(f"{key} = {'true' if value else 'false'}")
                replaced = True
                break
        if not replaced:
            new_body.append(line)

    for key in KEYS:
        if key not in seen:
            value = values.get(key, None)
            if value is not None:
                new_body.append(f"{key} = {'true' if value else 'false'}")

    new_lines = lines[: section_start + 1] + new_body + lines[section_end:]
    result = "\n".join(new_lines)
    return result.rstrip() + "\n"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _write_state(payload: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _chmod_private(STATE_DIR, stat.S_IRWXU)
    _atomic_write(STATE_PATH, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    _chmod_private(STATE_PATH, stat.S_IRUSR | stat.S_IWUSR)


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _backup_config(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.uwa-memory-guard-{stamp}.bak")
    shutil.copy2(path, backup)
    _chmod_private(backup, stat.S_IRUSR | stat.S_IWUSR)
    return backup


def disable(path: Path = CONFIG_PATH) -> None:
    before = _current_values(path)
    state = _load_state()
    if not state.get("active"):
        _write_state(
            {
                "active": True,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "previous": before,
            }
        )

    _backup_config(path)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = _replace_section_keys(
        text,
        {"generate_memories": False, "use_memories": False},
    )
    _atomic_write(path, updated)
    _chmod_private(path, stat.S_IRUSR | stat.S_IWUSR)
    print("CODEX_UWA_MEMORIES_DISABLED")
    print("generate_memories=false")
    print("use_memories=false")


def restore(path: Path = CONFIG_PATH) -> None:
    state = _load_state()
    previous = state.get("previous") if isinstance(state.get("previous"), dict) else None
    if not previous:
        print("CODEX_UWA_MEMORY_GUARD_NO_SAVED_STATE")
        return

    restore_values: dict[str, bool | None] = {}
    for key in KEYS:
        value = previous.get(key, None)
        restore_values[key] = value if isinstance(value, bool) else None

    _backup_config(path)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = _replace_section_keys(text, restore_values)
    _atomic_write(path, updated)
    _chmod_private(path, stat.S_IRUSR | stat.S_IWUSR)

    state["active"] = False
    state["restored_at"] = datetime.now(timezone.utc).isoformat()
    _write_state(state)
    print("CODEX_UWA_MEMORIES_RESTORED")
    for key in KEYS:
        value = restore_values[key]
        print(f"{key}={'unset' if value is None else str(value).lower()}")


def status(path: Path = CONFIG_PATH) -> None:
    values = _current_values(path)
    state = _load_state()
    print(f"guard_active={str(bool(state.get('active'))).lower()}")
    for key in KEYS:
        value = values.get(key, None)
        print(f"{key}={'unset' if value is None else str(value).lower()}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("disable", "restore", "status"))
    args = parser.parse_args()

    if args.action == "disable":
        disable()
    elif args.action == "restore":
        restore()
    else:
        status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
