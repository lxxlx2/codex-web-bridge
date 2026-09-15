#!/usr/bin/env python3
"""Switch Codex between UWA override and normal ChatGPT-account mode.

The repository owns both directions of the provider switch:

* ``uwa`` updates only the small set of top-level Codex keys needed by the
  bridge, replaces the managed ``[model_providers.uwa]`` table, preserves all
  unrelated Desktop/plugin/MCP/project configuration, and records private
  restore state for UWA-only policy/context overrides.
* ``official`` is intentionally operator-light on macOS: quit ChatGPT Desktop /
  Codex, stop only the verified UWA listener, restore saved Codex Memories and
  pre-UWA non-model overrides, remove top-level provider/model/reasoning pins,
  and reopen Desktop automatically.

Authentication is never modified. The UWA provider definition is kept in
``official`` mode so switching back remains cheap. Config backups and private
restore state live outside the public repository.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import time
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Sequence

try:
    from tools.codex_uwa_memory_guard import restore as restore_memories
    from tools.codex_uwa_lifecycle import stop_uwa as stop_uwa_lifecycle
except ModuleNotFoundError:
    from codex_uwa_memory_guard import restore as restore_memories
    from codex_uwa_lifecycle import stop_uwa as stop_uwa_lifecycle

OFFICIAL_PIN_KEYS = {"model_provider", "model", "model_reasoning_effort"}
AUTO_COMPACT_SCOPE_KEY = "model_auto_compact_token_limit_scope"
UWA_RESTORE_KEYS = {
    "approval_policy",
    "sandbox_mode",
    "model_context_window",
    "model_auto_compact_token_limit",
    AUTO_COMPACT_SCOPE_KEY,
    "model_catalog_json",
}
ROOT_KEYS = OFFICIAL_PIN_KEYS  # backward-compatible public constant/tests

UWA_ROOT_VALUES: tuple[tuple[str, str], ...] = (
    ("model", '"chatgpt"'),
    ("model_provider", '"uwa"'),
    ("model_reasoning_effort", '"high"'),
    ("approval_policy", '"on-request"'),
    ("sandbox_mode", '"workspace-write"'),
    # Codex defaults this to ``total``. Browser-backed Responses include a
    # sizeable stable prefix (tools/instructions) in sampled usage, so charging
    # that prefix against every post-compaction turn can immediately retrigger
    # auto-compaction even after the compacted history itself is well below the
    # threshold. ``body_after_prefix`` is Codex's native carried-window mode and
    # still keeps the full context-window hard cap independent.
    (AUTO_COMPACT_SCOPE_KEY, '"body_after_prefix"'),
)

UWA_PROVIDER_TABLE = """[model_providers.uwa]
name = "Universal Web API"
base_url = "http://127.0.0.1:8199/v1"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
request_max_retries = 0
stream_max_retries = 0
stream_idle_timeout_ms = 300000
"""

REPO_ROOT = Path(__file__).resolve().parents[1]
UWA_PORT = 8199
DESKTOP_APPS = ("ChatGPT", "Codex")
STATE_VERSION = 1

Runner = Callable[..., subprocess.CompletedProcess[str]]
Sleeper = Callable[[float], None]


def default_config_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


def default_state_path() -> Path:
    return Path.home() / ".uwa" / "codex-provider-restore.json"


def default_legacy_official_path() -> Path:
    return Path.home() / ".uwa" / "config.official.toml"


def _split_root_and_sections(text: str) -> tuple[list[str], list[str]]:
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.lstrip().startswith("["):
            return lines[:index], lines[index:]
    return lines, []


def _key_name(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return ""
    return stripped.split("=", 1)[0].strip()


def _key_rhs(line: str) -> str:
    return line.split("=", 1)[1].strip()


def _top_provider(text: str) -> str | None:
    root, _ = _split_root_and_sections(text)
    for line in root:
        if _key_name(line) != "model_provider":
            continue
        value = _key_rhs(line)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            return value[1:-1]
        return value
    return None


def _root_entry(text: str, key: str) -> dict[str, object]:
    root, _ = _split_root_and_sections(text)
    for line in root:
        if _key_name(line) == key:
            return {"present": True, "rhs": _key_rhs(line)}
    return {"present": False, "rhs": None}


def _validate_toml(text: str) -> None:
    if not text.strip():
        return
    tomllib.loads(text)


def _table_header(line: str) -> str | None:
    stripped = line.strip()
    if not (stripped.startswith("[") and stripped.endswith("]")):
        return None
    if stripped.startswith("[[") and stripped.endswith("]]" ):
        return stripped[2:-2].strip()
    return stripped[1:-1].strip()


def _strip_table_prefix(lines: list[str], prefix: str) -> list[str]:
    out: list[str] = []
    skipping = False
    for line in lines:
        header = _table_header(line)
        if header is not None:
            skipping = header == prefix or header.startswith(prefix + ".")
        if not skipping:
            out.append(line)
    return out


def _build_root_override(
    text: str,
    *,
    remove_keys: set[str],
    values: Sequence[tuple[str, str]] = (),
    remove_uwa_profile: bool = False,
) -> tuple[str, list[str]]:
    root, sections = _split_root_and_sections(text)
    cleaned: list[str] = []
    for line in root:
        key = _key_name(line)
        if key in remove_keys:
            continue
        if remove_uwa_profile and key == "profile":
            value = _key_rhs(line)
            if value in {'"uwa"', "'uwa'"}:
                continue
        cleaned.append(line)

    prefix = [f"{key} = {value}\n" for key, value in values]
    if prefix and cleaned and any(line.strip() for line in cleaned):
        prefix.append("\n")
    return "".join(prefix + cleaned), sections


def _normalize_join(root_text: str, sections: list[str]) -> str:
    combined = root_text + "".join(sections)
    return combined.rstrip() + "\n" if combined.strip() else ""


def _capture_restore_state(text: str) -> dict[str, object]:
    root, _ = _split_root_and_sections(text)
    entries: dict[str, dict[str, object]] = {
        key: {"present": False, "rhs": None} for key in sorted(UWA_RESTORE_KEYS)
    }
    for line in root:
        key = _key_name(line)
        if key in UWA_RESTORE_KEYS:
            entries[key] = {"present": True, "rhs": _key_rhs(line)}
    return {"version": STATE_VERSION, "root": entries}


def _write_state(path: Path, state: Mapping[str, object]) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, path)
    path.chmod(0o600)


def _load_state(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    path = path.expanduser()
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != STATE_VERSION or not isinstance(data.get("root"), dict):
        raise RuntimeError(f"unsupported provider restore state: {path}")
    return data


def _upgrade_existing_restore_state(path: Path, current_text: str) -> bool:
    """Add newly managed scope to an older state before overwriting UWA config.

    Older V1 state files predate ``model_auto_compact_token_limit_scope``. When
    the operator is already in UWA mode, the current config is still the only
    source that can preserve an explicit pre-migration scope. Capture it before
    ``uwa_text`` replaces the root value.
    """

    path = path.expanduser()
    if not path.exists():
        return False
    data = _load_state(path)
    assert data is not None
    root = data.get("root")
    assert isinstance(root, dict)
    if AUTO_COMPACT_SCOPE_KEY in root:
        return False
    root[AUTO_COMPACT_SCOPE_KEY] = _root_entry(current_text, AUTO_COMPACT_SCOPE_KEY)
    _write_state(path, data)
    return True


def _restore_entries(state: Mapping[str, object] | None) -> dict[str, dict[str, object]] | None:
    if state is None:
        return None
    root = state.get("root")
    if not isinstance(root, dict):
        raise RuntimeError("provider restore state is missing root entries")
    result: dict[str, dict[str, object]] = {}
    for key in UWA_RESTORE_KEYS:
        entry = root.get(key)
        # Backward compatibility for a state created before UWA managed this
        # scope. Such a state must not authorize official_text to delete a scope
        # that the old switch never owned. A normal UWA re-apply upgrades the
        # state first via _upgrade_existing_restore_state().
        if entry is None and key == AUTO_COMPACT_SCOPE_KEY:
            result[key] = {"managed": False, "present": False, "rhs": None}
            continue
        if not isinstance(entry, dict) or not isinstance(entry.get("present"), bool):
            raise RuntimeError(f"provider restore state is invalid for {key}")
        present = bool(entry["present"])
        rhs = entry.get("rhs")
        if present and not isinstance(rhs, str):
            raise RuntimeError(f"provider restore state is missing value for {key}")
        result[key] = {"managed": True, "present": present, "rhs": rhs if present else None}
    return result


def official_text(
    text: str,
    *,
    restore_state: Mapping[str, object] | None = None,
) -> str:
    restore = _restore_entries(restore_state)
    remove_keys = set(OFFICIAL_PIN_KEYS)
    values: list[tuple[str, str]] = []

    if restore is not None:
        for key in sorted(UWA_RESTORE_KEYS):
            entry = restore[key]
            if entry.get("managed", True):
                remove_keys.add(key)
                if entry["present"]:
                    values.append((key, str(entry["rhs"])))

    root_text, sections = _build_root_override(
        text,
        remove_keys=remove_keys,
        values=values,
    )
    updated = _normalize_join(root_text, sections)
    _validate_toml(updated)
    return updated


def uwa_text(text: str) -> str:
    remove_keys = set(OFFICIAL_PIN_KEYS) | set(UWA_RESTORE_KEYS)
    root_text, sections = _build_root_override(
        text,
        remove_keys=remove_keys,
        values=UWA_ROOT_VALUES,
        remove_uwa_profile=True,
    )
    sections = _strip_table_prefix(sections, "model_providers.uwa")

    body = _normalize_join(root_text, sections).rstrip()
    if body:
        body += "\n\n"
    updated = body + UWA_PROVIDER_TABLE.rstrip() + "\n"
    _validate_toml(updated)
    return updated


def _backup_config(config_path: Path, label: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = config_path.with_name(f"{config_path.name}.{label}-{timestamp}")
    shutil.copy2(config_path, backup)
    return backup


def write_official(
    config_path: Path,
    *,
    restore_state: Mapping[str, object] | None = None,
) -> tuple[Path | None, bool]:
    if not config_path.exists():
        return None, False

    original = config_path.read_text(encoding="utf-8")
    _validate_toml(original)
    updated = official_text(original, restore_state=restore_state)
    if updated == original:
        return None, False

    backup = _backup_config(config_path, "before-official")
    config_path.write_text(updated, encoding="utf-8")
    return backup, True


def write_uwa(
    config_path: Path,
    *,
    state_path: Path | None = None,
    legacy_official_path: Path | None = None,
) -> tuple[Path | None, bool, bool]:
    config_path = config_path.expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    original = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    _validate_toml(original)

    state_written = False
    if state_path is not None:
        state_path = state_path.expanduser()
        if _top_provider(original) != "uwa":
            _write_state(state_path, _capture_restore_state(original))
            state_written = True
        elif state_path.exists():
            state_written = _upgrade_existing_restore_state(state_path, original)
        elif legacy_official_path is not None:
            legacy_official_path = legacy_official_path.expanduser()
            if legacy_official_path.exists():
                legacy_text = legacy_official_path.read_text(encoding="utf-8")
                _validate_toml(legacy_text)
                _write_state(state_path, _capture_restore_state(legacy_text))
                state_written = True

    updated = uwa_text(original)
    if updated == original:
        return None, False, state_written

    backup: Path | None = None
    if config_path.exists():
        backup = _backup_config(config_path, "before-uwa")
    config_path.write_text(updated, encoding="utf-8")
    return backup, True, state_written


def top_level_status(text: str) -> dict[str, str]:
    root, _ = _split_root_and_sections(text)
    result: dict[str, str] = {}
    for line in root:
        key = _key_name(line)
        if key in ROOT_KEYS:
            result[key] = line.split("=", 1)[1].strip()
    return result


def _run(
    args: Sequence[str],
    *,
    runner: Runner = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    return runner(
        list(args),
        capture_output=True,
        text=True,
        check=False,
    )


def _process_running(app_name: str, *, runner: Runner = subprocess.run) -> bool:
    return _run(["pgrep", "-x", app_name], runner=runner).returncode == 0


def quit_desktop_apps(
    *,
    runner: Runner = subprocess.run,
    sleeper: Sleeper = time.sleep,
    timeout_sec: float = 10.0,
) -> list[str]:
    """Gracefully quit known Codex-capable desktop apps, then enforce shutdown."""

    if platform.system() != "Darwin":
        return []

    stopped: list[str] = []
    for app_name in DESKTOP_APPS:
        if not _process_running(app_name, runner=runner):
            continue

        _run(
            ["osascript", "-e", f'tell application "{app_name}" to quit'],
            runner=runner,
        )

        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if not _process_running(app_name, runner=runner):
                break
            sleeper(0.25)

        if _process_running(app_name, runner=runner):
            _run(["pkill", "-TERM", "-x", app_name], runner=runner)
            sleeper(0.5)

        if _process_running(app_name, runner=runner):
            _run(["pkill", "-KILL", "-x", app_name], runner=runner)
            sleeper(0.25)

        if _process_running(app_name, runner=runner):
            raise RuntimeError(f"failed to stop desktop application: {app_name}")
        stopped.append(app_name)

    return stopped



def stop_uwa_listener(
    *,
    repo_root: Path = REPO_ROOT,
    runner: Runner = subprocess.run,
    sleeper: Sleeper = time.sleep,
    timeout_sec: float = 10.0,
) -> list[int]:
    stopped = stop_uwa_lifecycle(
        repo_root=repo_root,
        port=UWA_PORT,
        timeout_sec=timeout_sec,
        runner=runner,
        sleeper=sleeper,
    )
    return list(stopped)


def open_desktop_app(*, runner: Runner = subprocess.run) -> str:
    """Open ChatGPT Desktop, falling back to a standalone Codex app if present."""

    if platform.system() != "Darwin":
        return "SKIPPED_NON_MACOS"

    errors: list[str] = []
    for app_name in DESKTOP_APPS:
        result = _run(["open", "-a", app_name], runner=runner)
        if result.returncode == 0:
            return app_name
        detail = (result.stderr or result.stdout or "not found").strip()
        errors.append(f"{app_name}: {detail}")
    raise RuntimeError("unable to open ChatGPT/Codex Desktop; " + "; ".join(errors))


def switch_to_official(
    config_path: Path,
    *,
    automate_desktop: bool = True,
    automate_uwa_stop: bool = True,
    state_path: Path | None = None,
    quit_fn: Callable[[], list[str]] | None = None,
    stop_fn: Callable[[], list[int]] | None = None,
    restore_fn: Callable[[Path], None] | None = None,
    open_fn: Callable[[], str] | None = None,
) -> tuple[Path | None, bool, list[str], list[int], str]:
    """Perform the full official-account mode switch with minimal operator work."""

    quit_fn = quit_fn or quit_desktop_apps
    stop_fn = stop_fn or stop_uwa_listener
    restore_fn = restore_fn or restore_memories
    open_fn = open_fn or open_desktop_app

    stopped_apps: list[str] = []
    stopped_pids: list[int] = []

    if automate_desktop:
        stopped_apps = quit_fn()
    if automate_uwa_stop:
        stopped_pids = stop_fn()

    restore_fn(config_path)
    restore_state = _load_state(state_path)
    backup, changed = write_official(config_path, restore_state=restore_state)

    if state_path is not None and state_path.expanduser().exists():
        state_path.expanduser().unlink()

    reopened = "SKIPPED"
    if automate_desktop:
        reopened = open_fn()

    return backup, changed, stopped_apps, stopped_pids, reopened


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["official", "uwa", "status"])
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--state", type=Path, default=default_state_path())
    parser.add_argument(
        "--legacy-official",
        type=Path,
        default=default_legacy_official_path(),
        help="optional one-time source for restore-only root values when migrating an already-active legacy UWA config",
    )
    parser.add_argument(
        "--no-desktop-restart",
        action="store_true",
        help="do not automatically quit/reopen ChatGPT Desktop",
    )
    parser.add_argument(
        "--no-stop-uwa",
        action="store_true",
        help="do not automatically stop the verified TCP 8199 UWA listener",
    )
    args = parser.parse_args()

    path: Path = args.config.expanduser()
    state_path: Path = args.state.expanduser()

    if args.action == "status":
        if not path.exists():
            print(f"CONFIG={path}")
            print("STATUS=missing")
            return 0
        status = top_level_status(path.read_text(encoding="utf-8"))
        print(f"CONFIG={path}")
        for key in sorted(ROOT_KEYS):
            print(f"{key}={status.get(key, '<default>')}")
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        print(f"{AUTO_COMPACT_SCOPE_KEY}={parsed.get(AUTO_COMPACT_SCOPE_KEY, '<default>')}")
        print(f"UWA_RESTORE_STATE={'PRESENT' if state_path.exists() else 'ABSENT'}")
        return 0

    if args.action == "uwa":
        try:
            backup, changed, state_written = write_uwa(
                path,
                state_path=state_path,
                legacy_official_path=args.legacy_official,
            )
        except Exception as exc:
            print("UWA_MODE_SWITCH=FAIL")
            print(f"ERROR={exc}")
            return 1

        print(f"CONFIG={path}")
        print(f"UWA_MODE_CHANGED={'YES' if changed else 'NO'}")
        if backup is not None:
            print(f"BACKUP={backup}")
        print(
            f"UWA_RESTORE_STATE={'UPDATED' if state_written else ('PRESENT' if state_path.exists() else 'ABSENT')}"
        )
        print('model_provider="uwa"')
        print('model="chatgpt"')
        print('model_reasoning_effort="high"')
        print(f'{AUTO_COMPACT_SCOPE_KEY}="body_after_prefix"')
        print("AUTH=UNCHANGED")
        return 0

    try:
        backup, changed, stopped_apps, stopped_pids, reopened = switch_to_official(
            path,
            automate_desktop=not args.no_desktop_restart,
            automate_uwa_stop=not args.no_stop_uwa,
            state_path=state_path,
        )
    except Exception as exc:
        print("OFFICIAL_MODE_SWITCH=FAIL")
        print(f"ERROR={exc}")
        return 1

    print(f"CONFIG={path}")
    print(f"OFFICIAL_MODE_CHANGED={'YES' if changed else 'NO'}")
    if backup is not None:
        print(f"BACKUP={backup}")
    print(f"UWA_LISTENER_STOPPED={','.join(map(str, stopped_pids)) if stopped_pids else 'NONE'}")
    print(f"DESKTOP_APPS_STOPPED={','.join(stopped_apps) if stopped_apps else 'NONE'}")
    print(f"DESKTOP_REOPENED={reopened}")
    print("AUTH=UNCHANGED")
    print("MODEL_SELECTION=ACCOUNT_DEFAULT_UI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())