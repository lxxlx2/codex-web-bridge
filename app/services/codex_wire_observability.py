"""Private, local-only observability for Codex Responses traffic.

The default mode stores metadata only under ``~/.uwa``. It is designed to answer
questions such as "did Codex receive a real function_call or only assistant
text?" without writing prompts, source code, command bodies, cookies, or tokens.

Full capture exists only as an explicit opt-in for local debugging. Full capture
can contain prompts, source snippets and tool output and must never be committed.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


_TRACE_COUNTER = itertools.count(1)
_TRACE_MODES = {"off", "metadata", "full"}
_SENSITIVE_KEY_RE = re.compile(
    r"(?:authorization|cookie|token|secret|password|api[_-]?key|session)",
    re.IGNORECASE,
)


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = str(os.getenv(name, str(default)) or str(default)).strip()
    try:
        value = int(raw)
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def trace_mode() -> str:
    raw = str(os.getenv("UWA_CODEX_WIRE_TRACE", "metadata") or "metadata").strip().lower()
    return raw if raw in _TRACE_MODES else "metadata"


def trace_dir() -> Path:
    raw = str(os.getenv("UWA_CODEX_WIRE_TRACE_DIR", "") or "").strip()
    if raw:
        return Path(os.path.expanduser(raw)).resolve()
    return (Path.home() / ".uwa" / "debug" / "codex-wire").resolve()


def trace_max_files() -> int:
    return _env_int("UWA_CODEX_WIRE_TRACE_MAX_FILES", 400, 20, 5000)


def trace_status() -> Dict[str, Any]:
    return {
        "mode": trace_mode(),
        "directory": str(trace_dir()),
        "max_files": trace_max_files(),
        "metadata_only_by_default": True,
        "full_capture_warning": (
            "full mode may contain prompts, source snippets and tool output; keep it local"
        ),
    }


def new_trace_id() -> str:
    return f"{int(time.time() * 1000)}-{os.getpid()}-{next(_TRACE_COUNTER):04d}"


def _model_dump(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump(mode="json")
            return dumped if isinstance(dumped, dict) else {}
        except Exception:
            pass
    if hasattr(value, "dict"):
        try:
            dumped = value.dict()
            return dumped if isinstance(dumped, dict) else {}
        except Exception:
            pass
    return dict(value) if isinstance(value, dict) else {}


def _tool_names(tools: Any) -> List[str]:
    names: List[str] = []
    for item in tools if isinstance(tools, list) else []:
        if not isinstance(item, dict):
            continue
        function_data = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = str(function_data.get("name") or item.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _count_text_chars(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return sum(_count_text_chars(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_count_text_chars(item) for item in value)
    return 0


def _summarize_input(value: Any) -> Dict[str, Any]:
    if isinstance(value, list):
        items = value
    elif value in (None, ""):
        items = []
    else:
        items = [value]

    roles: Dict[str, int] = {}
    types: Dict[str, int] = {}
    function_call_outputs = 0
    for item in items:
        if not isinstance(item, dict):
            types[type(item).__name__] = types.get(type(item).__name__, 0) + 1
            continue
        role = str(item.get("role") or "").strip().lower()
        item_type = str(item.get("type") or "").strip().lower()
        if role:
            roles[role] = roles.get(role, 0) + 1
        if item_type:
            types[item_type] = types.get(item_type, 0) + 1
        if item_type == "function_call_output":
            function_call_outputs += 1

    return {
        "item_count": len(items),
        "roles": roles,
        "types": types,
        "text_chars": _count_text_chars(value),
        "function_call_output_count": function_call_outputs,
    }


def summarize_responses_request(body: Any, required_tool: Optional[str] = None) -> Dict[str, Any]:
    data = _model_dump(body)
    reasoning = data.get("reasoning") if isinstance(data.get("reasoning"), dict) else {}
    return {
        "model": str(data.get("model") or ""),
        "stream": bool(data.get("stream")),
        "store": data.get("store"),
        "previous_response_id_present": bool(str(data.get("previous_response_id") or "").strip()),
        "reasoning_effort": str(reasoning.get("effort") or ""),
        "tool_names": _tool_names(data.get("tools")),
        "required_tool": str(required_tool or ""),
        "instructions_chars": len(str(data.get("instructions") or "")),
        "input": _summarize_input(data.get("input")),
    }


def _json_argument_summary(raw_arguments: Any) -> Dict[str, Any]:
    if isinstance(raw_arguments, dict):
        arguments = raw_arguments
        raw_text = json.dumps(raw_arguments, ensure_ascii=False, separators=(",", ":"))
    else:
        raw_text = str(raw_arguments or "{}")
        try:
            parsed = json.loads(raw_text)
        except Exception:
            parsed = None
        arguments = parsed if isinstance(parsed, dict) else {}

    return {
        "argument_keys": sorted(str(key) for key in arguments.keys()),
        "argument_chars": len(raw_text),
        "arguments_sha256_16": hashlib.sha256(raw_text.encode("utf-8", "replace")).hexdigest()[:16],
        "has_workdir": "workdir" in arguments,
        "workdir_is_root": str(arguments.get("workdir") or "").strip() == "/",
        "has_cwd": "cwd" in arguments,
        "cwd_is_root": str(arguments.get("cwd") or "").strip() == "/",
    }


def _record_function_call(
    item: Any,
    calls: List[Dict[str, Any]],
    seen: set,
) -> None:
    if not isinstance(item, dict):
        return
    if str(item.get("type") or "").strip().lower() != "function_call":
        return
    name = str(item.get("name") or "").strip()
    call_id = str(item.get("call_id") or item.get("id") or "").strip()
    argument_summary = _json_argument_summary(item.get("arguments"))
    dedupe_key = (
        call_id,
        name,
        argument_summary["arguments_sha256_16"],
    )
    if dedupe_key in seen:
        return
    seen.add(dedupe_key)
    calls.append(
        {
            "name": name,
            "call_id_present": bool(call_id),
            **argument_summary,
        }
    )


def _output_text_chars_from_item(item: Any) -> int:
    if not isinstance(item, dict):
        return 0
    if str(item.get("type") or "").strip().lower() != "message":
        return 0
    total = 0
    content = item.get("content")
    for part in content if isinstance(content, list) else []:
        if not isinstance(part, dict):
            continue
        if str(part.get("type") or "").strip().lower() in {"output_text", "text"}:
            total += len(str(part.get("text") or ""))
    return total


def summarize_responses_sse(chunks: Iterable[Any]) -> Dict[str, Any]:
    text_parts: List[str] = []
    for chunk in chunks:
        if isinstance(chunk, bytes):
            text_parts.append(chunk.decode("utf-8", "replace"))
        else:
            text_parts.append(str(chunk or ""))
    text = "".join(text_parts)

    event_counts: Dict[str, int] = {}
    event_order: List[str] = []
    function_calls: List[Dict[str, Any]] = []
    seen_calls: set = set()
    output_text_chars = 0
    response_status = ""
    response_id_present = False

    for block in re.split(r"\r?\n\r?\n", text):
        if not block.strip() or block.lstrip().startswith(":"):
            continue
        event_name = ""
        data_lines: List[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if not event_name:
            continue
        event_counts[event_name] = event_counts.get(event_name, 0) + 1
        event_order.append(event_name)
        if not data_lines:
            continue
        try:
            payload = json.loads("\n".join(data_lines))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue

        item = payload.get("item")
        _record_function_call(item, function_calls, seen_calls)
        output_text_chars += _output_text_chars_from_item(item)

        response = payload.get("response")
        if isinstance(response, dict):
            response_status = str(response.get("status") or response_status)
            response_id_present = response_id_present or bool(str(response.get("id") or "").strip())
            output = response.get("output")
            for output_item in output if isinstance(output, list) else []:
                _record_function_call(output_item, function_calls, seen_calls)
                output_text_chars += _output_text_chars_from_item(output_item)

    return {
        "event_counts": event_counts,
        "event_order": event_order,
        "function_calls": function_calls,
        "function_call_names": [item["name"] for item in function_calls if item.get("name")],
        "output_text_chars": output_text_chars,
        "response_status": response_status,
        "response_id_present": response_id_present,
        "raw_sse_chars": len(text),
    }


def _redact_for_disk(value: Any, key_hint: str = "") -> Any:
    if key_hint and _SENSITIVE_KEY_RE.search(key_hint):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(key): _redact_for_disk(item, str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_for_disk(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_for_disk(item) for item in value]
    return value


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def _write_private_json(path: Path, payload: Dict[str, Any]) -> None:
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(encoded)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _prune_trace_files(directory: Path) -> None:
    files = sorted(
        (path for path in directory.glob("*.json") if path.is_file()),
        key=lambda path: (path.stat().st_mtime, path.name),
    )
    excess = len(files) - trace_max_files()
    for path in files[: max(0, excess)]:
        try:
            path.unlink()
        except OSError:
            pass


def write_trace_attempt(
    *,
    trace_id: str,
    attempt: int,
    request_summary: Dict[str, Any],
    response_summary: Dict[str, Any],
    full_request: Optional[Any] = None,
    raw_sse: Optional[str] = None,
) -> None:
    mode = trace_mode()
    if mode == "off":
        return

    directory = trace_dir()
    _ensure_private_dir(directory)
    prefix = f"{trace_id}-attempt{int(attempt):02d}"

    request_payload: Dict[str, Any] = {
        "trace_id": trace_id,
        "attempt": int(attempt),
        "captured_at_unix": time.time(),
        "mode": mode,
        "summary": request_summary,
    }
    response_payload: Dict[str, Any] = {
        "trace_id": trace_id,
        "attempt": int(attempt),
        "captured_at_unix": time.time(),
        "mode": mode,
        "summary": response_summary,
    }

    if mode == "full":
        request_payload["full_request"] = _redact_for_disk(_model_dump(full_request))
        response_payload["raw_sse"] = str(raw_sse or "")

    _write_private_json(directory / f"{prefix}-request.json", request_payload)
    _write_private_json(directory / f"{prefix}-response.json", response_payload)
    _prune_trace_files(directory)


__all__ = [
    "new_trace_id",
    "summarize_responses_request",
    "summarize_responses_sse",
    "trace_dir",
    "trace_mode",
    "trace_status",
    "write_trace_attempt",
]
