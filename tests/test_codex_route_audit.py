import importlib.util
import json
import os
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "codex_route_audit.py"
SPEC = importlib.util.spec_from_file_location("codex_route_audit", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
route_audit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = route_audit
SPEC.loader.exec_module(route_audit)


def _jsonl(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(item) + "\n" for item in items),
        encoding="utf-8",
    )


def _trace(path: Path, captured: float, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "captured_at_unix": captured,
                "mode": "metadata",
                "summary": summary,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_authoritative_events_ignore_nested_historical_reasoning_values(tmp_path):
    path = tmp_path / "rollout.jsonl"
    _jsonl(
        path,
        [
            {
                "type": "session_meta",
                "payload": {
                    "model_provider": "openai",
                    "model": "gpt-6-astra",
                    "reasoning_effort": "ultra",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "debug": {
                        "model_provider": "uwa",
                        "model": "chatgpt",
                        "reasoning_effort": ["low", "medium", "xhigh"],
                    }
                },
            },
        ],
    )

    route = route_audit.extract_session_route(path)

    assert route.provider == "openai"
    assert route.model == "gpt-6-astra"
    assert route.effort == "ultra"


def test_turn_context_updates_active_model_and_effort_but_preserves_provider(tmp_path):
    path = tmp_path / "rollout.jsonl"
    _jsonl(
        path,
        [
            {
                "type": "session_meta",
                "payload": {"model_provider": "uwa"},
            },
            {
                "type": "turn_context",
                "payload": {"model": "chatgpt", "effort": "high"},
            },
        ],
    )

    route = route_audit.extract_session_route(path)

    assert route == route_audit.Route("uwa", "chatgpt", "high")


def test_thread_settings_applied_is_an_explicit_authoritative_override():
    original = route_audit.Route("openai", "gpt-6-astra", "ultra")
    event = {
        "type": "event_msg",
        "payload": {
            "type": "thread_settings_applied",
            "thread_settings": {
                "model_provider_id": "uwa",
                "model": "chatgpt",
                "reasoning_effort": "high",
            },
        },
    }

    assert route_audit.apply_authoritative_event(original, event) == route_audit.Route(
        "uwa", "chatgpt", "high"
    )


def test_latest_session_route_respects_marker_epoch(tmp_path):
    root = tmp_path / "sessions"
    old_path = root / "old.jsonl"
    new_path = root / "new.jsonl"
    _jsonl(
        old_path,
        [
            {
                "type": "session_meta",
                "payload": {
                    "model_provider": "openai",
                    "model": "gpt-6-astra",
                    "reasoning_effort": "ultra",
                },
            }
        ],
    )
    _jsonl(
        new_path,
        [
            {
                "type": "session_meta",
                "payload": {"model_provider": "uwa"},
            },
            {
                "type": "turn_context",
                "payload": {"model": "chatgpt", "effort": "high"},
            },
        ],
    )
    os.utime(old_path, (100.0, 100.0))
    os.utime(new_path, (300.0, 300.0))

    session = route_audit.latest_session_route(
        root,
        since_epoch=200.0,
        max_age_hours=1.0,
        now=400.0,
    )

    assert session is not None
    assert session.route == route_audit.Route("uwa", "chatgpt", "high")
    assert len(session.identity_hash) == 12
    assert "new" not in session.identity_hash


def test_wire_activity_filters_pre_marker_records(tmp_path):
    trace = tmp_path / "trace"
    _trace(
        trace / "old-request.json",
        90.0,
        {"model": "chatgpt", "reasoning_effort": "medium"},
    )
    _trace(
        trace / "new-request.json",
        110.0,
        {"model": "chatgpt", "reasoning_effort": "high"},
    )
    _trace(
        trace / "new-response.json",
        111.0,
        {"response_status": "completed"},
    )

    activity = route_audit.scan_wire_activity(trace, since_epoch=100.0)

    assert activity.request_count == 1
    assert activity.response_count == 1
    assert activity.latest_model == "chatgpt"
    assert activity.latest_effort == "high"
    assert activity.latest_status == "completed"


def test_uwa_expectation_requires_live_wire_request():
    session = route_audit.SessionRoute(
        route=route_audit.Route("uwa", "chatgpt", "high"),
        mtime=100.0,
        identity_hash="deadbeefcafe",
    )
    no_wire = route_audit.WireActivity(0, 0, "", "", "")

    passed, failures = route_audit.expectation_result(
        session,
        no_wire,
        expect_provider="uwa",
        expect_model="chatgpt",
        expect_effort="high",
    )

    assert passed is False
    assert failures == ["uwa_wire_request"]

    with_wire = route_audit.WireActivity(1, 1, "chatgpt", "high", "completed")
    passed, failures = route_audit.expectation_result(
        session,
        with_wire,
        expect_provider="uwa",
        expect_model="chatgpt",
        expect_effort="high",
    )
    assert passed is True
    assert failures == []


def test_expectation_fails_closed_on_wrong_model_or_effort():
    session = route_audit.SessionRoute(
        route=route_audit.Route("openai", "gpt-6-astra", "high"),
        mtime=100.0,
        identity_hash="deadbeefcafe",
    )
    wire = route_audit.WireActivity(0, 0, "", "", "")

    passed, failures = route_audit.expectation_result(
        session,
        wire,
        expect_provider="openai",
        expect_model="gpt-6-astra",
        expect_effort="ultra",
    )

    assert passed is False
    assert failures == ["effort"]


def test_marker_is_private_and_contains_only_route_metadata(tmp_path):
    marker = tmp_path / "route-marker.json"
    route = route_audit.Route("uwa", "chatgpt", "high")

    captured = route_audit.write_marker(marker, config=route, now=1234.5)
    payload = json.loads(marker.read_text(encoding="utf-8"))

    assert captured == 1234.5
    assert marker.stat().st_mode & 0o777 == 0o600
    assert payload == {
        "version": 1,
        "captured_at_unix": 1234.5,
        "configured_route": {
            "provider": "uwa",
            "model": "chatgpt",
            "effort": "high",
        },
    }
    serialized = json.dumps(payload)
    assert "thread" not in serialized.lower()
    assert "prompt" not in serialized.lower()
    assert "command" not in serialized.lower()


def test_print_report_exposes_hash_not_raw_rollout_path(capsys):
    session = route_audit.SessionRoute(
        route=route_audit.Route("openai", "gpt-6-astra", "ultra"),
        mtime=100.0,
        identity_hash="0123456789ab",
    )
    route_audit.print_report(
        config=route_audit.Route("uwa", "chatgpt", "high"),
        session=session,
        wire=route_audit.WireActivity(0, 0, "", "", ""),
        health=route_audit.Health("healthy", True),
        since_epoch=0.0,
        now=120.0,
    )

    output = capsys.readouterr().out
    assert "CONFIG_SESSION_ROUTE=MISMATCH" in output
    assert "LATEST_SESSION_IDENTITY_HASH=0123456789ab" in output
    assert "/Users/" not in output
    assert ".jsonl" not in output
