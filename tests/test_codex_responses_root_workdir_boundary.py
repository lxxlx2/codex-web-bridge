import json

from app.api.codex_responses import _sanitize_codex_root_workdirs


def _payload(arguments):
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_pwd",
                            "type": "function",
                            "function": {
                                "name": "exec_command",
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                },
            }
        ]
    }


def _arguments(payload):
    raw = payload["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    return json.loads(raw)


def test_boundary_strips_accidental_root_workdir_for_current_workspace_request():
    messages = [{"role": "user", "content": "必须使用 exec_command 执行 pwd，只返回真实输出。"}]
    cleaned = _sanitize_codex_root_workdirs(
        _payload({"cmd": "pwd", "workdir": "/"}),
        messages,
    )
    assert _arguments(cleaned) == {"cmd": "pwd"}


def test_boundary_preserves_explicit_root_request():
    messages = [{"role": "user", "content": "Use exec_command with workdir=/ and run pwd from filesystem root."}]
    cleaned = _sanitize_codex_root_workdirs(
        _payload({"cmd": "pwd", "workdir": "/"}),
        messages,
    )
    assert _arguments(cleaned) == {"cmd": "pwd", "workdir": "/"}


def test_boundary_preserves_non_root_workdir():
    messages = [{"role": "user", "content": "Run pwd in the current project."}]
    cleaned = _sanitize_codex_root_workdirs(
        _payload({"cmd": "pwd", "workdir": "subdir"}),
        messages,
    )
    assert _arguments(cleaned) == {"cmd": "pwd", "workdir": "subdir"}


def test_boundary_does_not_mutate_source_payload():
    source = _payload({"cmd": "pwd", "workdir": "/"})
    cleaned = _sanitize_codex_root_workdirs(
        source,
        [{"role": "user", "content": "exec_command pwd"}],
    )
    assert _arguments(cleaned) == {"cmd": "pwd"}
    assert _arguments(source) == {"cmd": "pwd", "workdir": "/"}
