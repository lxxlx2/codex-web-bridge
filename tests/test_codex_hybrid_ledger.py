import importlib.util
import json
import os
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "codex_hybrid_ledger.py"
SPEC = importlib.util.spec_from_file_location("codex_hybrid_ledger", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ledger = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ledger
SPEC.loader.exec_module(ledger)


def test_record_payload_hashes_workspace_and_keeps_only_route_metadata(tmp_path):
    workspace = tmp_path / "private-workspace"
    workspace.mkdir()
    payload = ledger.record_payload(
        event="handoff",
        source=ledger.Route("openai", "gpt-6-astra", "low"),
        target=ledger.Route("uwa", "chatgpt", "high"),
        workspace=workspace,
        session_identity_hash="deadbeefcafe",
        timestamp=123.0,
    )

    assert payload["version"] == 1
    assert payload["event"] == "handoff"
    assert payload["source"] == {
        "provider": "openai",
        "model": "gpt-6-astra",
        "effort": "low",
    }
    assert payload["target"] == {
        "provider": "uwa",
        "model": "chatgpt",
        "effort": "high",
    }
    assert payload["session_identity_hash"] == "deadbeefcafe"
    assert len(payload["workspace_hash"]) == 12
    serialized = json.dumps(payload)
    assert str(workspace) not in serialized
    assert "prompt" not in serialized.lower()
    assert "command" not in serialized.lower()
    assert "tool_output" not in serialized.lower()


def test_append_record_creates_private_bounded_ledger(tmp_path):
    path = tmp_path / "ledger.jsonl"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    for index in range(ledger.MAX_RECORDS + 5):
        payload = ledger.record_payload(
            event="probe",
            source=ledger.Route("uwa", "chatgpt", "high"),
            target=ledger.Route("uwa", "chatgpt", "high"),
            workspace=workspace,
            timestamp=float(index),
        )
        ledger.append_record(path, payload)

    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(records) == ledger.MAX_RECORDS
    assert records[0]["timestamp"] == 5.0
    assert records[-1]["timestamp"] == float(ledger.MAX_RECORDS + 4)
    assert path.stat().st_mode & 0o777 == 0o600


def test_latest_record_returns_last_valid_record(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_text(
        "not-json\n"
        + json.dumps({"version": 1, "event": "start"})
        + "\n"
        + json.dumps({"version": 1, "event": "complete"})
        + "\n"
    )
    assert ledger.latest_record(path)["event"] == "complete"


def test_session_identity_requires_prehashed_hex():
    assert ledger.validate_hash("") == ""
    assert ledger.validate_hash("ABCDEF12") == "abcdef12"
    try:
        ledger.validate_hash("raw/thread/id")
    except ValueError:
        pass
    else:
        raise AssertionError("raw identifiers must be rejected")
