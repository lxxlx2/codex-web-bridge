import os
import sqlite3

from app.services.codex_responses_state import (
    continuity_status,
    load_response_messages,
    store_response_messages,
)


def _configure(monkeypatch, tmp_path):
    db = tmp_path / "private" / "codex.sqlite3"
    monkeypatch.setenv("UWA_CODEX_RESPONSES_PERSIST", "true")
    monkeypatch.setenv("UWA_CODEX_RESPONSES_STATE_DB", str(db))
    monkeypatch.setenv("UWA_CODEX_RESPONSES_STATE_TTL_SEC", "600")
    monkeypatch.setenv("UWA_CODEX_RESPONSES_STATE_MAX_ENTRIES", "32")
    monkeypatch.setenv("UWA_CODEX_RESPONSES_STATE_MAX_RECORD_BYTES", "65536")
    return db


def test_store_and_load_private_continuation(monkeypatch, tmp_path):
    db = _configure(monkeypatch, tmp_path)
    messages = [
        {"role": "user", "content": "synthetic request"},
        {"role": "assistant", "content": "synthetic response"},
    ]

    assert store_response_messages("resp_test", messages) is True
    assert load_response_messages("resp_test") == messages
    assert db.exists()

    if os.name != "nt":
        assert db.stat().st_mode & 0o077 == 0
        assert db.parent.stat().st_mode & 0o077 == 0


def test_expired_continuation_is_pruned(monkeypatch, tmp_path):
    db = _configure(monkeypatch, tmp_path)
    assert store_response_messages(
        "resp_old",
        [{"role": "user", "content": "old"}],
    ) is True

    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "UPDATE codex_responses_state SET stored_at = stored_at - 3600 WHERE response_id = ?",
            ("resp_old",),
        )
        conn.commit()
    finally:
        conn.close()

    assert load_response_messages("resp_old") is None


def test_oversized_record_is_not_persisted(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    monkeypatch.setenv("UWA_CODEX_RESPONSES_STATE_MAX_RECORD_BYTES", "65536")
    huge = "x" * 70000
    assert store_response_messages(
        "resp_large",
        [{"role": "user", "content": huge}],
    ) is False
    assert load_response_messages("resp_large") is None


def test_status_exposes_metadata_not_local_path(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    assert store_response_messages(
        "resp_status",
        [{"role": "user", "content": "status"}],
    ) is True

    status = continuity_status()
    assert status["enabled"] is True
    assert status["entries"] == 1
    assert status["ttl_sec"] == 600
    assert "path" not in status
    assert "serialized" not in status
