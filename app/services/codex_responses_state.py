"""Private local persistence for Codex Responses continuation state.

The Codex web bridge needs to survive UWA process restarts without making the
public repository a storage location for prompts, source code, or tool output.
This module therefore stores only local runtime state under ~/.uwa by default.

Security properties:
- disabled only when explicitly configured false
- parent directory is created with mode 0700 when supported
- database/WAL/SHM files are chmod 0600 when supported
- bounded retention and entry count
- bounded single-record size
- no network access
- no Git writes
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


_LOCK = threading.RLock()
_SCHEMA = """
CREATE TABLE IF NOT EXISTS codex_responses_state (
    response_id TEXT PRIMARY KEY,
    stored_at REAL NOT NULL,
    serialized TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_codex_responses_state_stored_at
ON codex_responses_state(stored_at);
"""


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def persistence_enabled() -> bool:
    return _env_bool("UWA_CODEX_RESPONSES_PERSIST", True)


def retention_seconds() -> int:
    return _env_int(
        "UWA_CODEX_RESPONSES_STATE_TTL_SEC",
        7 * 24 * 60 * 60,
        minimum=300,
        maximum=90 * 24 * 60 * 60,
    )


def max_entries() -> int:
    return _env_int(
        "UWA_CODEX_RESPONSES_STATE_MAX_ENTRIES",
        4096,
        minimum=16,
        maximum=50000,
    )


def max_record_bytes() -> int:
    return _env_int(
        "UWA_CODEX_RESPONSES_STATE_MAX_RECORD_BYTES",
        8 * 1024 * 1024,
        minimum=64 * 1024,
        maximum=64 * 1024 * 1024,
    )


def database_path() -> Path:
    configured = str(os.getenv("UWA_CODEX_RESPONSES_STATE_DB") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".uwa" / "codex_responses.sqlite3").resolve()


def _safe_chmod(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except (OSError, NotImplementedError):
        pass


def _prepare_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _safe_chmod(path.parent, 0o700)


def _secure_sqlite_files(path: Path) -> None:
    for candidate in (
        path,
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
    ):
        if candidate.exists():
            _safe_chmod(candidate, 0o600)


def _connect() -> sqlite3.Connection:
    path = database_path()
    _prepare_parent(path)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(_SCHEMA)
    _secure_sqlite_files(path)
    return conn


def _prune(conn: sqlite3.Connection, *, now: Optional[float] = None) -> None:
    cutoff = float(now if now is not None else time.time()) - retention_seconds()
    conn.execute("DELETE FROM codex_responses_state WHERE stored_at < ?", (cutoff,))
    limit = max_entries()
    conn.execute(
        """
        DELETE FROM codex_responses_state
        WHERE response_id NOT IN (
            SELECT response_id
            FROM codex_responses_state
            ORDER BY stored_at DESC
            LIMIT ?
        )
        """,
        (limit,),
    )


def store_response_messages(response_id: str, messages: List[Dict[str, Any]]) -> bool:
    """Persist a complete Responses conversation snapshot for one response id."""

    if not persistence_enabled():
        return False
    key = str(response_id or "").strip()
    if not key:
        return False
    try:
        serialized = json.dumps(messages or [], ensure_ascii=False)
    except (TypeError, ValueError):
        return False
    if len(serialized.encode("utf-8")) > max_record_bytes():
        return False

    with _LOCK:
        conn = _connect()
        try:
            now = time.time()
            _prune(conn, now=now)
            conn.execute(
                """
                INSERT INTO codex_responses_state(response_id, stored_at, serialized)
                VALUES (?, ?, ?)
                ON CONFLICT(response_id) DO UPDATE SET
                    stored_at=excluded.stored_at,
                    serialized=excluded.serialized
                """,
                (key, now, serialized),
            )
            _prune(conn, now=now)
            conn.commit()
        finally:
            conn.close()
            _secure_sqlite_files(database_path())
    return True


def load_response_messages(response_id: str) -> Optional[List[Dict[str, Any]]]:
    """Load a persisted conversation snapshot, or None when absent/expired."""

    if not persistence_enabled():
        return None
    key = str(response_id or "").strip()
    if not key:
        return None

    with _LOCK:
        conn = _connect()
        try:
            _prune(conn)
            row = conn.execute(
                "SELECT serialized FROM codex_responses_state WHERE response_id = ?",
                (key,),
            ).fetchone()
            conn.commit()
        finally:
            conn.close()
            _secure_sqlite_files(database_path())

    if row is None:
        return None
    try:
        value = json.loads(str(row[0]))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(value, list):
        return None
    return [item for item in value if isinstance(item, dict)]


def clear_persisted_state() -> int:
    """Delete all private Codex continuation rows and return the removed count."""

    if not persistence_enabled() and not database_path().exists():
        return 0
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute("SELECT COUNT(*) FROM codex_responses_state").fetchone()
            count = int(row[0] if row else 0)
            conn.execute("DELETE FROM codex_responses_state")
            conn.commit()
        finally:
            conn.close()
            _secure_sqlite_files(database_path())
    return count


def continuity_status() -> Dict[str, Any]:
    """Return non-content metadata safe for the local diagnostics endpoint."""

    count = 0
    oldest_age_sec: Optional[int] = None
    if persistence_enabled() and database_path().exists():
        with _LOCK:
            conn = _connect()
            try:
                _prune(conn)
                row = conn.execute(
                    "SELECT COUNT(*), MIN(stored_at) FROM codex_responses_state"
                ).fetchone()
                conn.commit()
            finally:
                conn.close()
                _secure_sqlite_files(database_path())
        if row:
            count = int(row[0] or 0)
            if row[1] is not None:
                oldest_age_sec = max(0, int(time.time() - float(row[1])))

    return {
        "enabled": persistence_enabled(),
        "entries": count,
        "ttl_sec": retention_seconds(),
        "max_entries": max_entries(),
        "max_record_bytes": max_record_bytes(),
        "oldest_age_sec": oldest_age_sec,
    }
