#!/usr/bin/env python3
"""Versioned lifecycle manager for the local Codex/UWA bridge.

The old operator commands lived only in ``~/bin`` and could report a successful
restart while TCP 8199 was still served by stale Python bytecode.  This module
makes stop/start/restart verifiable and fail-closed:

* a listener is touched only when its cwd resolves to this repository;
* stop sends TERM, waits, escalates to KILL when needed, and requires the port
  to become empty before it reports success;
* restart always replaces the listener instead of reusing a merely healthy
  process;
* start requires a healthy UWA response and an owned listener before success;
* launcher PID state is best-effort metadata, never the authority for whether
  the service is actually stopped.

The public CLI is intended to be called by thin ``~/bin/codex-uwa*`` wrappers.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORT = 8199
DEFAULT_STATE_DIR = Path.home() / ".uwa"
DEFAULT_LOG_MAX_BYTES = 10_000_000
DEFAULT_STOP_TIMEOUT = 10.0
DEFAULT_START_TIMEOUT = 90.0

Runner = Callable[..., subprocess.CompletedProcess[str]]
Sleeper = Callable[[float], None]
Killer = Callable[[int, int], None]


@dataclass(frozen=True)
class StartResult:
    launcher_pid: int
    listener_pids: tuple[int, ...]


@dataclass(frozen=True)
class RestartResult:
    old_listener_pids: tuple[int, ...]
    start: StartResult


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


def listener_pids(
    port: int = DEFAULT_PORT,
    *,
    runner: Runner = subprocess.run,
) -> list[int]:
    result = _run(
        ["lsof", "-nP", f"-tiTCP:{port}", "-sTCP:LISTEN"],
        runner=runner,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"failed to inspect TCP {port} listeners")

    found: list[int] = []
    for raw in result.stdout.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            found.append(int(raw))
        except ValueError as exc:
            raise RuntimeError(f"unexpected lsof PID output: {raw!r}") from exc
    return sorted(set(found))


def process_cwd(
    pid: int,
    *,
    runner: Runner = subprocess.run,
) -> Path | None:
    result = _run(
        ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
        runner=runner,
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if line.startswith("n") and len(line) > 1:
            return Path(line[1:]).expanduser()
    return None


def process_command(
    pid: int,
    *,
    runner: Runner = subprocess.run,
) -> str:
    result = _run(["ps", "-o", "command=", "-p", str(pid)], runner=runner)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def process_ppid(
    pid: int,
    *,
    runner: Runner = subprocess.run,
) -> int | None:
    result = _run(["ps", "-o", "ppid=", "-p", str(pid)], runner=runner)
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _resolved(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except OSError:
        return path.expanduser().absolute()


def require_owned_listeners(
    pids: Sequence[int],
    *,
    repo_root: Path = REPO_ROOT,
    runner: Runner = subprocess.run,
) -> None:
    expected = _resolved(repo_root)
    for pid in pids:
        cwd = process_cwd(pid, runner=runner)
        if cwd is None or _resolved(cwd) != expected:
            raise RuntimeError(
                f"refusing to touch listener {pid}: cwd={cwd!s} expected={expected}"
            )


def _read_pidfile(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        pid = int(raw)
        return pid if pid > 1 else None
    except (OSError, ValueError):
        return None


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _owned_launcher_candidates(
    listener_ids: Sequence[int],
    *,
    repo_root: Path,
    pidfile: Path,
    runner: Runner,
) -> list[int]:
    """Return start.py/main.py ancestors that are proven to belong to this checkout."""

    expected = _resolved(repo_root)
    candidates: set[int] = set()

    saved = _read_pidfile(pidfile)
    if saved is not None and _pid_running(saved):
        cwd = process_cwd(saved, runner=runner)
        command = process_command(saved, runner=runner)
        if cwd is not None and _resolved(cwd) == expected and "start.py" in command:
            candidates.add(saved)

    for listener in listener_ids:
        current = listener
        for _ in range(6):
            parent = process_ppid(current, runner=runner)
            if parent is None or parent <= 1:
                break
            cwd = process_cwd(parent, runner=runner)
            command = process_command(parent, runner=runner)
            if cwd is None or _resolved(cwd) != expected:
                break
            if "start.py" in command or "main.py" in command:
                candidates.add(parent)
            current = parent

    return sorted(candidates)


def _signal_many(pids: Sequence[int], sig: int, *, killer: Killer = os.kill) -> None:
    for pid in pids:
        try:
            killer(pid, sig)
        except ProcessLookupError:
            continue


def _wait_for_empty_port(
    *,
    port: int,
    timeout_sec: float,
    runner: Runner,
    sleeper: Sleeper,
) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if not listener_pids(port, runner=runner):
            return True
        sleeper(0.25)
    return not listener_pids(port, runner=runner)


def stop_uwa(
    *,
    repo_root: Path = REPO_ROOT,
    port: int = DEFAULT_PORT,
    state_dir: Path = DEFAULT_STATE_DIR,
    timeout_sec: float = DEFAULT_STOP_TIMEOUT,
    runner: Runner = subprocess.run,
    sleeper: Sleeper = time.sleep,
    killer: Killer = os.kill,
) -> tuple[int, ...]:
    """Stop the real UWA listener and prove the port is empty before returning."""

    repo_root = _resolved(repo_root)
    state_dir = state_dir.expanduser()
    pidfile = state_dir / "uwa.pid"

    initial = listener_pids(port, runner=runner)
    require_owned_listeners(initial, repo_root=repo_root, runner=runner)
    launchers = _owned_launcher_candidates(
        initial,
        repo_root=repo_root,
        pidfile=pidfile,
        runner=runner,
    )

    # Stop launchers first so they cannot supervise or recreate a listener while
    # the listener itself is being terminated.
    _signal_many(launchers, signal.SIGTERM, killer=killer)
    _signal_many(initial, signal.SIGTERM, killer=killer)

    if not _wait_for_empty_port(
        port=port,
        timeout_sec=timeout_sec,
        runner=runner,
        sleeper=sleeper,
    ):
        remaining = listener_pids(port, runner=runner)
        require_owned_listeners(remaining, repo_root=repo_root, runner=runner)
        _signal_many(remaining, signal.SIGKILL, killer=killer)
        _signal_many(launchers, signal.SIGKILL, killer=killer)

        if not _wait_for_empty_port(
            port=port,
            timeout_sec=max(2.0, timeout_sec / 2),
            runner=runner,
            sleeper=sleeper,
        ):
            raise RuntimeError(
                f"TCP {port} still has listeners after TERM/KILL: "
                f"{listener_pids(port, runner=runner)}"
            )

    try:
        pidfile.unlink(missing_ok=True)
    except OSError as exc:
        raise RuntimeError(f"failed to remove stale pidfile {pidfile}: {exc}") from exc

    return tuple(initial)


def health_ok(port: int = DEFAULT_PORT, *, timeout_sec: float = 3.0) -> bool:
    url = f"http://127.0.0.1:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return False
    return bool(
        payload.get("service") == "healthy"
        and payload.get("browser", {}).get("connected") is True
    )


def _rotate_log(path: Path, *, max_bytes: int = DEFAULT_LOG_MAX_BYTES) -> None:
    try:
        if path.exists() and path.stat().st_size > max_bytes:
            old = path.with_name(path.name + ".old")
            old.unlink(missing_ok=True)
            path.replace(old)
    except OSError:
        # Rotation is useful but must not make lifecycle correctness depend on it.
        pass


def start_uwa(
    *,
    repo_root: Path = REPO_ROOT,
    port: int = DEFAULT_PORT,
    state_dir: Path = DEFAULT_STATE_DIR,
    timeout_sec: float = DEFAULT_START_TIMEOUT,
    python_executable: str | None = None,
    sleeper: Sleeper = time.sleep,
) -> StartResult:
    """Start UWA from this checkout and require healthy owned listener evidence."""

    repo_root = _resolved(repo_root)
    state_dir = state_dir.expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)

    existing = listener_pids(port)
    if existing:
        require_owned_listeners(existing, repo_root=repo_root)
        raise RuntimeError(
            f"TCP {port} already has UWA listener(s) {existing}; use restart, not start"
        )

    launcher = repo_root / "start.py"
    if not launcher.exists():
        raise RuntimeError(f"missing launcher: {launcher}")

    python_executable = python_executable or shutil.which("python3") or sys.executable
    log_path = state_dir / "uwa.log"
    pidfile = state_dir / "uwa.pid"
    _rotate_log(log_path)

    log_handle = log_path.open("a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            [python_executable, str(launcher)],
            cwd=str(repo_root),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            text=True,
        )
    finally:
        log_handle.close()

    pidfile.write_text(f"{proc.pid}\n", encoding="utf-8")

    deadline = time.monotonic() + timeout_sec
    last_pids: list[int] = []
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"UWA launcher exited before healthy: returncode={proc.returncode}; "
                f"see {log_path}"
            )

        last_pids = listener_pids(port)
        if last_pids:
            require_owned_listeners(last_pids, repo_root=repo_root)
            if health_ok(port):
                return StartResult(proc.pid, tuple(last_pids))
        sleeper(1.0)

    raise RuntimeError(
        f"UWA did not become healthy within {timeout_sec:.0f}s; "
        f"listeners={last_pids}; see {log_path}"
    )


def restart_uwa(
    *,
    repo_root: Path = REPO_ROOT,
    port: int = DEFAULT_PORT,
    state_dir: Path = DEFAULT_STATE_DIR,
    stop_timeout_sec: float = DEFAULT_STOP_TIMEOUT,
    start_timeout_sec: float = DEFAULT_START_TIMEOUT,
) -> RestartResult:
    old = stop_uwa(
        repo_root=repo_root,
        port=port,
        state_dir=state_dir,
        timeout_sec=stop_timeout_sec,
    )
    started = start_uwa(
        repo_root=repo_root,
        port=port,
        state_dir=state_dir,
        timeout_sec=start_timeout_sec,
    )

    overlap = set(old) & set(started.listener_pids)
    if overlap:
        raise RuntimeError(
            f"restart did not prove listener replacement; reused PID(s): {sorted(overlap)}"
        )
    return RestartResult(old, started)


def _status(
    *,
    repo_root: Path,
    port: int,
    runner: Runner = subprocess.run,
) -> int:
    pids = listener_pids(port, runner=runner)
    print(f"PORT={port}")
    print(f"LISTENER_PIDS={','.join(map(str, pids)) if pids else 'NONE'}")
    if not pids:
        print("STATUS=STOPPED")
        return 0

    try:
        require_owned_listeners(pids, repo_root=repo_root, runner=runner)
    except RuntimeError as exc:
        print("STATUS=FOREIGN_LISTENER")
        print(f"ERROR={exc}")
        return 2

    print(f"STATUS={'HEALTHY' if health_ok(port) else 'LISTENING_NOT_HEALTHY'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["status", "stop", "start", "restart"])
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--stop-timeout", type=float, default=DEFAULT_STOP_TIMEOUT)
    parser.add_argument("--start-timeout", type=float, default=DEFAULT_START_TIMEOUT)
    args = parser.parse_args()

    root = args.root.expanduser()
    state = args.state_dir.expanduser()

    try:
        if args.action == "status":
            return _status(repo_root=root, port=args.port)

        if args.action == "stop":
            stopped = stop_uwa(
                repo_root=root,
                port=args.port,
                state_dir=state,
                timeout_sec=args.stop_timeout,
            )
            print(f"STOPPED_LISTENERS={','.join(map(str, stopped)) if stopped else 'NONE'}")
            print("PORT_EMPTY=YES")
            return 0

        if args.action == "start":
            started = start_uwa(
                repo_root=root,
                port=args.port,
                state_dir=state,
                timeout_sec=args.start_timeout,
            )
            print(f"LAUNCHER_PID={started.launcher_pid}")
            print(f"LISTENER_PIDS={','.join(map(str, started.listener_pids))}")
            print("HEALTH=PASS")
            return 0

        result = restart_uwa(
            repo_root=root,
            port=args.port,
            state_dir=state,
            stop_timeout_sec=args.stop_timeout,
            start_timeout_sec=args.start_timeout,
        )
        print(
            "OLD_LISTENER_PIDS="
            + (",".join(map(str, result.old_listener_pids)) if result.old_listener_pids else "NONE")
        )
        print(f"NEW_LISTENER_PIDS={','.join(map(str, result.start.listener_pids))}")
        print("LISTENER_REPLACED=YES")
        print("HEALTH=PASS")
        return 0
    except Exception as exc:
        print(f"LIFECYCLE_{args.action.upper()}=FAIL")
        print(f"ERROR={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
