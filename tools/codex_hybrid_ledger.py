#!/usr/bin/env python3
"""Private metadata-only hybrid route transition ledger.

Records only bounded route metadata, a hashed workspace identity and an optional
already-hashed session identity. It never stores prompts, source code, command
bodies, tool output, raw workspace paths, raw thread ids, cookies or credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_LEDGER = Path.home() / ".uwa" / "codex-hybrid-route-ledger.jsonl"
VERSION = 1
ALLOWED_EVENTS = {"probe", "start", "quota_exhausted", "handoff", "switch", "complete"}
MAX_RECORDS = 256


@dataclass(frozen=True)
class Route:
    provider: str
    model: str
    effort: str

    def as_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model,
            "effort": self.effort,
        }


def clean(value: Any, *, limit: int = 80) -> str:
    text = str(value or "").strip()
    return text[:limit]


def workspace_hash(path: str | Path) -> str:
    resolved = str(Path(path).expanduser().resolve())
    return hashlib.sha256(resolved.encode("utf-8", "replace")).hexdigest()[:12]


def validate_hash(value: str) -> str:
    text = clean(value, limit=64)
    if not text:
        return ""
    allowed = set("0123456789abcdefABCDEF")
    if len(text) > 64 or any(ch not in allowed for ch in text):
        raise ValueError("session identity must already be a hex hash")
    return text.lower()


def record_payload(
    *,
    event: str,
    source: Route,
    target: Route,
    workspace: str | Path,
    session_identity_hash: str = "",
    timestamp: float | None = None,
) -> dict[str, Any]:
    event = clean(event, limit=32)
    if event not in ALLOWED_EVENTS:
        raise ValueError("unsupported ledger event")
    return {
        "version": VERSION,
        "timestamp": float(time.time() if timestamp is None else timestamp),
        "event": event,
        "source": source.as_dict(),
        "target": target.as_dict(),
        "session_identity_hash": validate_hash(session_identity_hash),
        "workspace_hash": workspace_hash(workspace),
    }


def _read_records(path: Path) -> list[dict[str, Any]]:
    path = path.expanduser()
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("version") == VERSION:
            records.append(item)
    return records[-MAX_RECORDS:]


def append_record(path: Path, payload: dict[str, Any]) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    records = _read_records(path)
    records.append(payload)
    records = records[-MAX_RECORDS:]
    encoded = "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in records)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(encoded)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def latest_record(path: Path = DEFAULT_LEDGER) -> dict[str, Any] | None:
    records = _read_records(path)
    return records[-1] if records else None


def is_private_mode(path: Path = DEFAULT_LEDGER) -> bool:
    path = path.expanduser()
    if not path.exists():
        return False
    return (path.stat().st_mode & 0o777) == 0o600


def print_record(record: dict[str, Any] | None, *, path: Path) -> None:
    if record is None:
        print("HYBRID_LEDGER_PRESENT=NO")
        return
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    target = record.get("target") if isinstance(record.get("target"), dict) else {}
    print("HYBRID_LEDGER_PRESENT=YES")
    print("HYBRID_LEDGER_PRIVATE_MODE=" + ("YES" if is_private_mode(path) else "NO"))
    print("LAST_EVENT=" + clean(record.get("event")))
    print("LAST_SOURCE_PROVIDER=" + clean(source.get("provider")))
    print("LAST_SOURCE_MODEL=" + clean(source.get("model")))
    print("LAST_SOURCE_EFFORT=" + clean(source.get("effort")))
    print("LAST_TARGET_PROVIDER=" + clean(target.get("provider")))
    print("LAST_TARGET_MODEL=" + clean(target.get("model")))
    print("LAST_TARGET_EFFORT=" + clean(target.get("effort")))
    print("LAST_WORKSPACE_HASH=" + clean(record.get("workspace_hash")))
    print("LAST_SESSION_IDENTITY_HASH=" + (clean(record.get("session_identity_hash")) or "NONE"))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    rec = sub.add_parser("record")
    rec.add_argument("--event", required=True, choices=sorted(ALLOWED_EVENTS))
    rec.add_argument("--workspace", required=True)
    rec.add_argument("--session-identity-hash", default="")
    for prefix in ("source", "target"):
        rec.add_argument(f"--{prefix}-provider", required=True)
        rec.add_argument(f"--{prefix}-model", required=True)
        rec.add_argument(f"--{prefix}-effort", required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    path: Path = args.ledger.expanduser()
    if args.command == "status":
        print_record(latest_record(path), path=path)
        return 0
    source = Route(clean(args.source_provider), clean(args.source_model), clean(args.source_effort))
    target = Route(clean(args.target_provider), clean(args.target_model), clean(args.target_effort))
    payload = record_payload(
        event=args.event,
        source=source,
        target=target,
        workspace=args.workspace,
        session_identity_hash=args.session_identity_hash,
    )
    append_record(path, payload)
    print("HYBRID_LEDGER_RECORD_WRITTEN=YES")
    print_record(payload, path=path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
