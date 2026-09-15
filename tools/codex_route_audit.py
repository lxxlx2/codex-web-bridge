#!/usr/bin/env python3
"""Metadata-only route audit for Codex official/UWA hybrid operation.

The helper intentionally reads only route metadata from local Codex rollout
JSONL, the managed Codex config, UWA health, and UWA's metadata-only wire trace.
It never prints prompts, source code, command bodies, tool output, raw thread
identifiers, raw rollout paths, cookies, or credentials.

Typical use:

    python3 tools/codex_route_audit.py status
    python3 tools/codex_route_audit.py mark
    python3 tools/codex_route_audit.py check \
        --expect-provider uwa --expect-model chatgpt --expect-effort high
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_CONFIG = Path.home() / ".codex" / "config.toml"
DEFAULT_SESSION_ROOT = Path.home() / ".codex"
DEFAULT_TRACE_DIR = Path.home() / ".uwa" / "debug" / "codex-wire"
DEFAULT_MARKER = Path.home() / ".uwa" / "route-audit-marker.json"
DEFAULT_HEALTH_URL = "http://127.0.0.1:8199/health"
DEFAULT_MAX_AGE_HOURS = 24.0
MARKER_VERSION = 1


@dataclass(frozen=True)
class Route:
    provider: str = ""
    model: str = ""
    effort: str = ""

    def complete(self) -> bool:
        return bool(self.provider and self.model and self.effort)


@dataclass(frozen=True)
class SessionRoute:
    route: Route
    mtime: float
    identity_hash: str


@dataclass(frozen=True)
class WireActivity:
    request_count: int
    response_count: int
    latest_model: str
    latest_effort: str
    latest_status: str


@dataclass(frozen=True)
class Health:
    state: str
    browser_connected: bool | None


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _hash_identity(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:12]


def read_config_route(path: Path = DEFAULT_CONFIG) -> Route:
    path = path.expanduser()
    if not path.exists():
        return Route()
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    return Route(
        provider=_clean(parsed.get("model_provider")),
        model=_clean(parsed.get("model")),
        effort=_clean(parsed.get("model_reasoning_effort")),
    )


def _payload(obj: dict[str, Any]) -> dict[str, Any]:
    payload = obj.get("payload")
    return payload if isinstance(payload, dict) else obj


def _apply_session_meta(route: Route, payload: dict[str, Any]) -> Route:
    provider = _clean(payload.get("model_provider")) or route.provider
    model = _clean(payload.get("model")) or route.model
    effort = (
        _clean(payload.get("reasoning_effort"))
        or _clean(payload.get("effort"))
        or route.effort
    )
    return Route(provider=provider, model=model, effort=effort)


def _apply_turn_context(route: Route, payload: dict[str, Any]) -> Route:
    # Codex's canonical metadata extraction treats TurnContext as authoritative
    # for model/reasoning, while provider normally comes from SessionMeta.
    provider = _clean(payload.get("model_provider")) or route.provider
    model = _clean(payload.get("model")) or route.model
    effort = (
        _clean(payload.get("effort"))
        or _clean(payload.get("reasoning_effort"))
        or route.effort
    )
    return Route(provider=provider, model=model, effort=effort)


def _apply_thread_settings(route: Route, payload: dict[str, Any]) -> Route:
    settings = payload.get("thread_settings")
    if not isinstance(settings, dict):
        settings = payload.get("settings")
    if not isinstance(settings, dict):
        return route
    return Route(
        provider=_clean(settings.get("model_provider_id"))
        or _clean(settings.get("model_provider"))
        or route.provider,
        model=_clean(settings.get("model")) or route.model,
        effort=_clean(settings.get("reasoning_effort"))
        or _clean(settings.get("effort"))
        or route.effort,
    )


def apply_authoritative_event(route: Route, obj: dict[str, Any]) -> Route:
    """Apply only Codex route-bearing metadata events.

    Do not recursively search arbitrary JSON values. This prevents historical
    model/reasoning strings embedded in unrelated event payloads from being
    mistaken for the active route.
    """

    event_type = _clean(obj.get("type")).lower()
    payload = _payload(obj)

    if event_type == "session_meta":
        return _apply_session_meta(route, payload)
    if event_type == "turn_context":
        return _apply_turn_context(route, payload)

    # Newer rollouts may persist a ThreadSettingsApplied event. Accept only the
    # explicit event type and its explicit thread_settings payload.
    if event_type == "event_msg":
        inner_type = _clean(payload.get("type")).lower()
        if inner_type in {"thread_settings_applied", "threadsettingsapplied"}:
            return _apply_thread_settings(route, payload)

    return route


def extract_session_route(path: Path) -> Route:
    route = Route()
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    route = apply_authoritative_event(route, obj)
    except OSError:
        return Route()
    return route


def iter_recent_jsonl(
    root: Path = DEFAULT_SESSION_ROOT,
    *,
    since_epoch: float = 0.0,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    now: float | None = None,
) -> Iterable[Path]:
    root = root.expanduser()
    if not root.exists():
        return []
    now = time.time() if now is None else float(now)
    oldest = now - max(0.0, float(max_age_hours)) * 3600.0
    threshold = max(float(since_epoch), oldest)
    paths: list[Path] = []
    for path in root.rglob("*.jsonl"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime >= threshold:
            paths.append(path)
    paths.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return paths


def latest_session_route(
    root: Path = DEFAULT_SESSION_ROOT,
    *,
    since_epoch: float = 0.0,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    now: float | None = None,
) -> SessionRoute | None:
    for path in iter_recent_jsonl(
        root,
        since_epoch=since_epoch,
        max_age_hours=max_age_hours,
        now=now,
    ):
        route = extract_session_route(path)
        if not (route.provider or route.model or route.effort):
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        return SessionRoute(
            route=route,
            mtime=mtime,
            identity_hash=_hash_identity(str(path.resolve())),
        )
    return None


def scan_wire_activity(
    trace_dir: Path = DEFAULT_TRACE_DIR,
    *,
    since_epoch: float = 0.0,
) -> WireActivity:
    trace_dir = trace_dir.expanduser()
    if not trace_dir.is_dir():
        return WireActivity(0, 0, "", "", "")

    request_count = 0
    response_count = 0
    latest_model = ""
    latest_effort = ""
    latest_status = ""
    latest_request_ts = -1.0
    latest_response_ts = -1.0

    for path in trace_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        captured = data.get("captured_at_unix")
        try:
            captured_ts = float(captured)
        except (TypeError, ValueError):
            continue
        if captured_ts < float(since_epoch):
            continue
        summary = data.get("summary")
        if not isinstance(summary, dict):
            continue
        if _clean(summary.get("request_kind")) == "metadata_helper":
            continue

        if path.name.endswith("-request.json"):
            request_count += 1
            if captured_ts >= latest_request_ts:
                latest_request_ts = captured_ts
                latest_model = _clean(summary.get("model"))
                latest_effort = _clean(summary.get("reasoning_effort"))
        elif path.name.endswith("-response.json"):
            response_count += 1
            if captured_ts >= latest_response_ts:
                latest_response_ts = captured_ts
                latest_status = _clean(summary.get("response_status"))

    return WireActivity(
        request_count=request_count,
        response_count=response_count,
        latest_model=latest_model,
        latest_effort=latest_effort,
        latest_status=latest_status,
    )


def read_uwa_health(url: str = DEFAULT_HEALTH_URL, *, timeout: float = 1.5) -> Health:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return Health("unavailable", None)
    if not isinstance(payload, dict):
        return Health("unknown", None)
    state = _clean(payload.get("service") or payload.get("status") or "unknown").lower()
    browser = payload.get("browser_connected")
    if not isinstance(browser, bool):
        browser_obj = payload.get("browser")
        if isinstance(browser_obj, dict) and isinstance(browser_obj.get("connected"), bool):
            browser = browser_obj["connected"]
        else:
            browser = None
    return Health(state or "unknown", browser)


def classify_config_session(config: Route, session: SessionRoute | None) -> str:
    if session is None or not session.route.provider:
        return "UNKNOWN"
    if not config.provider:
        return "UNKNOWN"
    return "MATCH" if config.provider == session.route.provider else "MISMATCH"


def expectation_result(
    session: SessionRoute | None,
    wire: WireActivity,
    *,
    expect_provider: str = "",
    expect_model: str = "",
    expect_effort: str = "",
) -> tuple[bool | None, list[str]]:
    requested = any((expect_provider, expect_model, expect_effort))
    if not requested:
        return None, []
    failures: list[str] = []
    if session is None:
        failures.append("no_session_metadata")
        return False, failures

    route = session.route
    if expect_provider and route.provider != expect_provider:
        failures.append("provider")
    if expect_model and route.model != expect_model:
        failures.append("model")
    if expect_effort and route.effort != expect_effort:
        failures.append("effort")

    # UWA route proof requires actual UWA wire activity after the marker. A
    # config/session label alone is not sufficient evidence that the live turn
    # reached UWA.
    if expect_provider == "uwa" and wire.request_count < 1:
        failures.append("uwa_wire_request")

    return not failures, failures


def _marker_payload(route: Route, captured_at: float) -> dict[str, Any]:
    return {
        "version": MARKER_VERSION,
        "captured_at_unix": captured_at,
        "configured_route": {
            "provider": route.provider,
            "model": route.model,
            "effort": route.effort,
        },
    }


def write_marker(path: Path = DEFAULT_MARKER, *, config: Route | None = None, now: float | None = None) -> float:
    path = path.expanduser()
    captured = time.time() if now is None else float(now)
    config = read_config_route() if config is None else config
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(_marker_payload(config, captured), ensure_ascii=False, indent=2) + "\n"
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(encoded)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return captured


def load_marker(path: Path = DEFAULT_MARKER) -> float:
    path = path.expanduser()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != MARKER_VERSION:
        raise RuntimeError("unsupported route audit marker")
    value = data.get("captured_at_unix")
    if not isinstance(value, (int, float)):
        raise RuntimeError("route audit marker missing captured_at_unix")
    return float(value)


def _fmt_bool(value: bool | None) -> str:
    if value is None:
        return "UNKNOWN"
    return "YES" if value else "NO"


def print_report(
    *,
    config: Route,
    session: SessionRoute | None,
    wire: WireActivity,
    health: Health,
    since_epoch: float,
    expectation: bool | None = None,
    failures: list[str] | None = None,
    now: float | None = None,
) -> None:
    now = time.time() if now is None else float(now)
    print("===== CODEX ROUTE AUDIT =====")
    print("CONFIGURED_PROVIDER=" + (config.provider or "UNKNOWN"))
    print("CONFIGURED_MODEL=" + (config.model or "UNKNOWN"))
    print("CONFIGURED_EFFORT=" + (config.effort or "UNKNOWN"))

    if session is None:
        print("LATEST_SESSION_PRESENT=NO")
        print("LATEST_SESSION_PROVIDER=UNKNOWN")
        print("LATEST_SESSION_MODEL=UNKNOWN")
        print("LATEST_SESSION_EFFORT=UNKNOWN")
        print("LATEST_SESSION_AGE_SECONDS=UNKNOWN")
        print("LATEST_SESSION_IDENTITY_HASH=UNKNOWN")
    else:
        print("LATEST_SESSION_PRESENT=YES")
        print("LATEST_SESSION_PROVIDER=" + (session.route.provider or "UNKNOWN"))
        print("LATEST_SESSION_MODEL=" + (session.route.model or "UNKNOWN"))
        print("LATEST_SESSION_EFFORT=" + (session.route.effort or "UNKNOWN"))
        print("LATEST_SESSION_AGE_SECONDS=" + str(max(0, int(now - session.mtime))))
        print("LATEST_SESSION_IDENTITY_HASH=" + session.identity_hash)

    print("CONFIG_SESSION_ROUTE=" + classify_config_session(config, session))
    print("UWA_HEALTH=" + health.state)
    print("UWA_BROWSER_CONNECTED=" + _fmt_bool(health.browser_connected))
    print("UWA_WIRE_SINCE_EPOCH=" + (str(int(since_epoch)) if since_epoch else "ALL_RECENT_TRACE"))
    print("UWA_WIRE_REQUEST_COUNT=" + str(wire.request_count))
    print("UWA_WIRE_RESPONSE_COUNT=" + str(wire.response_count))
    print("UWA_WIRE_LATEST_MODEL=" + (wire.latest_model or "UNKNOWN"))
    print("UWA_WIRE_LATEST_EFFORT=" + (wire.latest_effort or "UNKNOWN"))
    print("UWA_WIRE_LATEST_STATUS=" + (wire.latest_status or "UNKNOWN"))

    if expectation is not None:
        print("ROUTE_EXPECTATION_PASS=" + ("YES" if expectation else "NO"))
        print("ROUTE_EXPECTATION_FAILURES=" + (",".join(failures or []) or "NONE"))

    print("ROUTE_AUDIT_DONE")


def _report_for_args(args: argparse.Namespace, *, since_epoch: float) -> tuple[bool | None, list[str]]:
    config = read_config_route(args.config)
    session = latest_session_route(
        args.session_root,
        since_epoch=since_epoch,
        max_age_hours=args.max_age_hours,
    )
    wire = scan_wire_activity(args.trace_dir, since_epoch=since_epoch)
    health = read_uwa_health(args.health_url)
    expectation, failures = expectation_result(
        session,
        wire,
        expect_provider=_clean(args.expect_provider),
        expect_model=_clean(args.expect_model),
        expect_effort=_clean(args.expect_effort),
    )
    print_report(
        config=config,
        session=session,
        wire=wire,
        health=health,
        since_epoch=since_epoch,
        expectation=expectation,
        failures=failures,
    )
    return expectation, failures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["status", "mark", "check"])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--session-root", type=Path, default=DEFAULT_SESSION_ROOT)
    parser.add_argument("--trace-dir", type=Path, default=DEFAULT_TRACE_DIR)
    parser.add_argument("--marker", type=Path, default=DEFAULT_MARKER)
    parser.add_argument("--health-url", default=DEFAULT_HEALTH_URL)
    parser.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS)
    parser.add_argument("--expect-provider", default="")
    parser.add_argument("--expect-model", default="")
    parser.add_argument("--expect-effort", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.command == "mark":
        config = read_config_route(args.config)
        captured = write_marker(args.marker, config=config)
        print("ROUTE_MARKER_WRITTEN=YES")
        print("MARKER_PRIVATE_MODE=0600")
        print("MARKER_CONFIGURED_PROVIDER=" + (config.provider or "UNKNOWN"))
        print("MARKER_CONFIGURED_MODEL=" + (config.model or "UNKNOWN"))
        print("MARKER_CONFIGURED_EFFORT=" + (config.effort or "UNKNOWN"))
        print("MARKER_EPOCH=" + str(int(captured)))
        return 0

    if args.command == "check":
        try:
            since_epoch = load_marker(args.marker)
        except Exception as exc:
            print("ROUTE_AUDIT_CHECK=FAIL")
            print("ERROR=" + str(exc))
            return 2
    else:
        since_epoch = 0.0

    expectation, _ = _report_for_args(args, since_epoch=since_epoch)
    if expectation is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
