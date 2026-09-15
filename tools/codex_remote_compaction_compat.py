#!/usr/bin/env python3
"""Enable the narrow Codex remote-compaction capability shim for UWA.

The helper changes only the managed provider friendly name needed by affected
Codex versions while preserving the provider id, loopback URL, Responses wire
protocol and disabled OpenAI auth. It fails closed unless the managed contract
is exact.
"""

from __future__ import annotations

import argparse
import shutil
import tomllib
from datetime import datetime
from pathlib import Path

EXPECTED_PROVIDER_ID = "uwa"
EXPECTED_SOURCE_NAME = "Universal Web API"
COMPAT_PROVIDER_NAME = "Azure"
EXPECTED_BASE_URL = "http://127.0.0.1:8199/v1"
EXPECTED_WIRE_API = "responses"


def default_config_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


def _provider_table(parsed: dict) -> dict:
    providers = parsed.get("model_providers")
    if not isinstance(providers, dict):
        raise RuntimeError("model_providers table is missing")
    provider = providers.get(EXPECTED_PROVIDER_ID)
    if not isinstance(provider, dict):
        raise RuntimeError("model_providers.uwa table is missing")
    return provider


def _validate_contract(parsed: dict) -> dict:
    if parsed.get("model_provider") != EXPECTED_PROVIDER_ID:
        raise RuntimeError("top-level model_provider is not uwa")
    provider = _provider_table(parsed)
    name = provider.get("name")
    if name not in {EXPECTED_SOURCE_NAME, COMPAT_PROVIDER_NAME}:
        raise RuntimeError(f"unexpected UWA provider name: {name!r}")
    if provider.get("base_url") != EXPECTED_BASE_URL:
        raise RuntimeError("unexpected UWA base_url")
    if provider.get("wire_api") != EXPECTED_WIRE_API:
        raise RuntimeError("unexpected UWA wire_api")
    if provider.get("requires_openai_auth") is not False:
        raise RuntimeError("UWA requires_openai_auth must remain false")
    if provider.get("supports_websockets") is not False:
        raise RuntimeError("UWA supports_websockets must remain false")
    return provider


def _section_bounds(lines: list[str], header: str) -> tuple[int, int]:
    wanted = f"[{header}]"
    start = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if start is None:
            if stripped == wanted:
                start = index
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            return start, index
    if start is None:
        raise RuntimeError(f"section [{header}] not found")
    return start, len(lines)


def enable_text(text: str) -> tuple[str, bool]:
    parsed = tomllib.loads(text)
    provider = _validate_contract(parsed)
    if provider.get("name") == COMPAT_PROVIDER_NAME:
        return text, False
    lines = text.splitlines(keepends=True)
    start, end = _section_bounds(lines, "model_providers.uwa")
    name_indexes = []
    for index in range(start + 1, end):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.split("=", 1)[0].strip() == "name":
            name_indexes.append(index)
    if len(name_indexes) != 1:
        raise RuntimeError("managed UWA provider must contain exactly one name field")
    index = name_indexes[0]
    newline = "\n" if lines[index].endswith("\n") else ""
    lines[index] = f'name = "{COMPAT_PROVIDER_NAME}"{newline}'
    updated = "".join(lines)
    after = tomllib.loads(updated)
    _validate_contract(after)
    before_provider = dict(provider)
    after_provider = dict(_provider_table(after))
    before_provider["name"] = COMPAT_PROVIDER_NAME
    if after_provider != before_provider:
        raise RuntimeError("remote-compaction shim changed fields other than provider name")
    return updated, True


def enable_file(path: Path) -> tuple[Path | None, bool]:
    path = path.expanduser()
    if not path.exists():
        raise RuntimeError(f"Codex config does not exist: {path}")
    original = path.read_text(encoding="utf-8")
    updated, changed = enable_text(original)
    if not changed:
        return None, False
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = path.with_name(f"{path.name}.before-remote-compact-{timestamp}")
    shutil.copy2(path, backup)
    path.write_text(updated, encoding="utf-8")
    return backup, True


def status(path: Path) -> int:
    path = path.expanduser()
    print(f"CONFIG={path}")
    if not path.exists():
        print("REMOTE_COMPACTION_COMPAT=CONFIG_MISSING")
        return 1
    try:
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        provider = _validate_contract(parsed)
    except Exception as exc:
        print("REMOTE_COMPACTION_COMPAT=INVALID")
        print(f"ERROR={exc}")
        return 1
    enabled = provider.get("name") == COMPAT_PROVIDER_NAME
    print(f"UWA_PROVIDER_NAME={provider.get('name')}")
    print(f"UWA_BASE_URL={provider.get('base_url')}")
    print("UWA_REQUIRES_OPENAI_AUTH=false")
    print(f"REMOTE_COMPACTION_COMPAT={'ENABLED' if enabled else 'DISABLED'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["enable", "status"])
    parser.add_argument("--config", type=Path, default=default_config_path())
    args = parser.parse_args()
    if args.action == "status":
        return status(args.config)
    try:
        backup, changed = enable_file(args.config)
    except Exception as exc:
        print("REMOTE_COMPACTION_COMPAT=FAIL")
        print(f"ERROR={exc}")
        return 1
    print(f"CONFIG={args.config.expanduser()}")
    print(f"REMOTE_COMPACTION_COMPAT_CHANGED={'YES' if changed else 'NO'}")
    if backup is not None:
        print(f"BACKUP={backup}")
    print(f"UWA_PROVIDER_NAME={COMPAT_PROVIDER_NAME}")
    print(f"UWA_BASE_URL={EXPECTED_BASE_URL}")
    print("UWA_REQUIRES_OPENAI_AUTH=false")
    print("REMOTE_COMPACTION_COMPAT=ENABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
