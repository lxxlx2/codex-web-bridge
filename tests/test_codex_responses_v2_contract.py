import json

import pytest

from app.api.chat import ChatRequest, ResponsesRequest, _responses_request_to_chat_request
from app.api.codex_responses_v2 import (
    _browser_delta_chat_request,
    _browser_history_suffix_chat_request,
    _clone_for_required_tool_retry,
    _completed_response_has_no_output,
    _required_tool_failed_events,
    required_declared_tool,
)
from app.services.client_tool_policy import (
    looks_like_acceptance_completion_without_exact_sentinel,
    looks_like_incomplete_acceptance_continuation,
    looks_like_premature_acceptance_success,
    should_repair_client_workspace_refusal,
)
from app.services.codex_remote_compaction_v2 import (
    encode_compaction_envelope,
    rewrite_uwa_compaction_history,
)
from app.services.tool_calling_prompts import build_browser_messages_for_tools


def _tool(name: str):
    return {
        "type": "function",
        "name": name,
        "description": f"test {name}",
        "parameters": {
            "type": "object",
            "properties": {
                "cmd": {"type": "string"},
            },
            "required": ["cmd"],
        },
    }


def _body(text: str, *, tool_choice=None):
    return ResponsesRequest(
        model="chatgpt",
        stream=True,
        input=[
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            }
        ],
        tools=[_tool("exec_command"), _tool("write_stdin")],
        tool_choice=tool_choice,
    )


def test_required_tool_detects_explicit_chinese_exec_command_request():
    body = _body("必须使用 exec_command 执行 pwd，只返回真实输出。")
    assert required_declared_tool(body) == "exec_command"


def test_required_tool_detects_explicit_english_exec_command_request():
    body = _body("You must use exec_command to run pwd and return the real output.")
    assert required_declared_tool(body) == "exec_command"


def test_required_tool_does_not_force_tool_for_plain_reference():
    body = _body("Explain what exec_command means in this protocol.")
    assert required_declared_tool(body) == ""


def test_specific_tool_choice_is_always_treated_as_required():
    body = _body(
        "Run the requested operation.",
        tool_choice={"type": "function", "name": "exec_command"},
    )
    assert required_declared_tool(body) == "exec_command"


def test_retry_forces_declared_tool_as_incremental_chained_turn_without_mutating_original():
    body = _body("必须使用 exec_command 执行 pwd。")
    body.instructions = "original instructions"
    retry = _clone_for_required_tool_retry(
        body,
        "exec_command",
        attempt=2,
        previous_response_id="resp_attempt_one",
    )

    assert body.tool_choice is None
    assert body.instructions == "original instructions"
    assert body.previous_response_id is None

    assert retry.previous_response_id == "resp_attempt_one"
    assert retry.instructions is None
    assert retry.tool_choice == {"type": "function", "name": "exec_command"}
    assert isinstance(retry.input, list) and len(retry.input) == 1
    repair_text = retry.input[0]["content"]
    assert "exec_command" in repair_text
    assert "Do not simulate command output" in repair_text
    assert "omit `workdir`" in repair_text


def test_retry_preserves_compound_user_command_semantics():
    command = (
        "pwd && test -f .uwa_codex_acceptance "
        "&& test -d large_context"
    )

    body = _body(
        "必须通过客户端 exec_command 在当前工作区执行 "
        + command
        + "。不得拆分。"
    )

    retry = _clone_for_required_tool_retry(
        body,
        "exec_command",
        attempt=2,
        previous_response_id="resp_compound",
    )

    repair_text = retry.input[0]["content"]

    assert command in repair_text
    assert (
        "Do not weaken, shorten, split, substitute"
        in repair_text
    )
    assert (
        "partial probe such as `pwd` alone"
        in repair_text
    )
    assert (
        "<original_user_request>"
        in repair_text
    )


def test_required_tool_exhaustion_returns_structured_responses_failure():
    body = _body("必须使用 exec_command 执行 pwd。")
    frames = _required_tool_failed_events(body, "exec_command")
    combined = "".join(frames)

    assert "event: response.created" in combined
    assert "event: response.failed" in combined
    assert "required_client_tool_not_called" in combined
    assert "exec_command" in combined

    failed_data = frames[-1].split("data: ", 1)[1].strip()
    payload = json.loads(failed_data)
    assert payload["type"] == "response.failed"
    assert payload["response"]["status"] == "failed"


def test_completed_empty_output_is_rejected():
    assert _completed_response_has_no_output(
        "completed",
        {"output": []},
    )
    assert _completed_response_has_no_output(
        "completed",
        {"output": None},
    )
    assert not _completed_response_has_no_output(
        "completed",
        {"output": [{"type": "message"}]},
    )
    assert not _completed_response_has_no_output(
        "incomplete",
        {"output": []},
    )

def test_affinity_structured_tool_delta_carries_private_compacted_context():
    compacted = (
        "[Compacted prior context]\n"
        "[ACTIVE CONTINUATION STATE]\n"
        "Continue large_context/result.txt and only then return LARGE_CONTEXT_PASS."
    )
    state = ChatRequest(
        model="chatgpt",
        messages=[
            {"role": "assistant", "content": compacted},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_latest",
                        "type": "function",
                        "function": {
                            "name": "exec_command",
                            "arguments": '{"cmd":"pwd && ls -la large_context"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_latest",
                "name": "exec_command",
                "content": "Process exited with code 0\nFinal output: total 0\n",
            },
        ],
        tools=[],
    )
    source = ResponsesRequest(
        model="chatgpt",
        input=[
            {
                "type": "function_call_output",
                "call_id": "call_latest",
                "output": "Process exited with code 0\nFinal output: total 0\n",
            }
        ],
        tools=[_tool("exec_command")],
    )

    delta = _browser_delta_chat_request(state, source)
    tool_messages = [
        message
        for message in delta.messages
        if isinstance(message, dict)
        and message.get("role") == "tool"
    ]

    assert tool_messages
    assert (
        tool_messages[-1]["_uwa_compacted_continuation_context"]
        == compacted
    )


def _synthetic_restart_response_history(*, include_readback: bool) -> ResponsesRequest:
    """Use Responses items shaped like a restart turn, with synthetic values only."""

    items = [
        {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        "Use exec_command to run pwd && test -f .uwa_codex_acceptance "
                        "&& test -d context. After that succeeds, write "
                        "context/result.txt, perform a separate byte readback, and "
                        "only then reply CONTEXT_PASS."
                    ),
                }
            ],
        },
        {
            "type": "function_call",
            "call_id": "call_synthetic_validate",
            "name": "exec_command",
            "arguments": json.dumps(
                {"cmd": "pwd && test -f .uwa_codex_acceptance && test -d context"}
            ),
        },
        {
            "type": "function_call_output",
            "call_id": "call_synthetic_validate",
            "output": "Process exited with code 0\nFinal output: /synthetic\n",
        },
        {
            "type": "function_call",
            "call_id": "call_synthetic_write",
            "name": "exec_command",
            "arguments": json.dumps(
                {"cmd": "printf '%s\\n' 'SYNTHETIC-7319' > context/result.txt"}
            ),
        },
        {
            "type": "function_call_output",
            "call_id": "call_synthetic_write",
            "output": "Process exited with code 0\nFinal output:\n",
        },
    ]
    if include_readback:
        items.extend(
            [
                {
                    "type": "function_call",
                    "call_id": "call_synthetic_read",
                    "name": "exec_command",
                    "arguments": json.dumps(
                        {"cmd": "od -An -tx1 -v context/result.txt"}
                    ),
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_synthetic_read",
                    "output": (
                        "Process exited with code 0\n"
                        "Final output: 53 59 4e 54 48 45 54 49 43 2d 37 33 31 39 0a\n"
                    ),
                },
            ]
        )
    return ResponsesRequest(model="chatgpt", input=items, tools=[_tool("exec_command")])


def test_affinity_restart_delta_retains_proven_write_and_pending_byte_readback():
    full = _synthetic_restart_response_history(include_readback=False)
    state = _responses_request_to_chat_request(full, stream=False)
    assert looks_like_incomplete_acceptance_continuation(
        "ACCEPTANCE_INCOMPLETE", state.messages
    )
    source = ResponsesRequest(
        model="chatgpt",
        previous_response_id="resp_synthetic_prior",
        input=[full.input[-1]],
        tools=[_tool("exec_command")],
    )

    delta = _browser_delta_chat_request(state, source)

    # The web conversation already has the earlier history. Keep its visible
    # delta short while retaining trusted history for local policy decisions.
    assert [message["role"] for message in delta.messages] == ["assistant", "tool"]
    assert looks_like_incomplete_acceptance_continuation(
        "ACCEPTANCE_INCOMPLETE", delta.messages
    )
    assert looks_like_premature_acceptance_success("CONTEXT_PASS", delta.messages)
    browser_messages = build_browser_messages_for_tools(
        messages=delta.messages,
        tools=[_tool("exec_command")],
        tool_choice="auto",
    )
    assert "_uwa_synthetic_acceptance_state" not in json.dumps(browser_messages)


def test_affinity_restart_delta_recognizes_completed_byte_readback():
    full = _synthetic_restart_response_history(include_readback=True)
    state = _responses_request_to_chat_request(full, stream=False)
    assert looks_like_acceptance_completion_without_exact_sentinel(
        "The file is verified.", state.messages
    )
    source = ResponsesRequest(
        model="chatgpt",
        previous_response_id="resp_synthetic_prior",
        input=[full.input[-1]],
        tools=[_tool("exec_command")],
    )

    delta = _browser_delta_chat_request(state, source)

    assert [message["role"] for message in delta.messages] == ["assistant", "tool"]
    assert not looks_like_premature_acceptance_success(
        "CONTEXT_PASS", delta.messages
    )
    assert looks_like_acceptance_completion_without_exact_sentinel(
        "The file is verified.", delta.messages
    )


def test_full_history_affinity_suffix_retains_pending_byte_readback():
    full = _synthetic_restart_response_history(include_readback=False)
    state = _responses_request_to_chat_request(full, stream=False)

    # A full-history 0.156 continuation can reuse an affined Web conversation
    # by sending only the unmatched suffix after the validation pair.
    suffix = _browser_history_suffix_chat_request(state, 3)

    assert [message["role"] for message in suffix.messages] == ["assistant", "tool"]
    assert looks_like_incomplete_acceptance_continuation(
        "ACCEPTANCE_INCOMPLETE", suffix.messages
    )
    assert looks_like_premature_acceptance_success("CONTEXT_PASS", suffix.messages)


def test_compaction_checkpoint_fresh_replay_requires_post_write_byte_readback():
    before = _synthetic_restart_response_history(include_readback=False)
    checkpoint = {
        "type": "compaction",
        "encrypted_content": encode_compaction_envelope(
            "[ACTIVE CONTINUATION STATE]\n"
            "Continue context/result.txt and only then reply CONTEXT_PASS. "
            "The byte readback is still pending."
        ),
    }
    source = [before.input[0], checkpoint, *before.input[1:]]
    replay = rewrite_uwa_compaction_history(source)
    state = _responses_request_to_chat_request(
        ResponsesRequest(
            model="chatgpt", input=replay, tools=[_tool("exec_command")]
        ),
        stream=False,
    )

    # The old user item was dropped at the checkpoint. The local policy must
    # use the current paired commands, not the summary's claim about progress.
    assert state.messages[0]["role"] == "assistant"
    assert looks_like_premature_acceptance_success(
        "CONTEXT_PASS", state.messages
    )
    assert looks_like_incomplete_acceptance_continuation(
        "CONTEXT_PASS", state.messages
    )

    source_delta = ResponsesRequest(
        model="chatgpt",
        previous_response_id="resp_synthetic_checkpoint",
        input=[before.input[-1]],
        tools=[_tool("exec_command")],
    )
    delta = _browser_delta_chat_request(state, source_delta)
    assert looks_like_premature_acceptance_success(
        "CONTEXT_PASS", delta.messages
    )
    assert "_uwa_synthetic_acceptance_state" in delta.messages[-1]
    browser_messages = build_browser_messages_for_tools(
        messages=delta.messages,
        tools=[_tool("exec_command")],
        tool_choice="auto",
    )
    assert "_uwa_synthetic_acceptance_state" not in json.dumps(browser_messages)

    completed = _synthetic_restart_response_history(include_readback=True)
    completed_replay = rewrite_uwa_compaction_history(
        [completed.input[0], checkpoint, *completed.input[1:]]
    )
    completed_state = _responses_request_to_chat_request(
        ResponsesRequest(
            model="chatgpt",
            input=completed_replay,
            tools=[_tool("exec_command")],
        ),
        stream=False,
    )
    assert not looks_like_premature_acceptance_success(
        "CONTEXT_PASS", completed_state.messages
    )


def test_authenticated_checkpoint_restores_write_then_tracks_later_byte_readback(
    monkeypatch, tmp_path
):
    from app.services import codex_remote_compaction_v2 as remote

    monkeypatch.setattr(
        remote, "_ACCEPTANCE_CHECKPOINT_KEY_PATH", tmp_path / "checkpoint.key"
    )
    summary = (
        "[ACTIVE CONTINUATION STATE]\n"
        "The pending byte readback precedes CONTEXT_PASS."
    )
    state = {
        "marker": "CONTEXT_PASS",
        "result_path": "context/result.txt",
        "validated": True,
        "written": True,
        "readback": False,
    }
    checkpoint = {
        "type": "compaction",
        "encrypted_content": encode_compaction_envelope(
            summary, lineage="1" * 32, acceptance_state=state
        ),
    }

    def replay(items):
        return _responses_request_to_chat_request(
            ResponsesRequest(
                model="chatgpt",
                input=rewrite_uwa_compaction_history(items),
                tools=[_tool("exec_command")],
            ),
            stream=False,
        ).messages

    messages = replay([checkpoint])
    assert messages[0]["_uwa_synthetic_acceptance_state"] == state
    assert looks_like_incomplete_acceptance_continuation("CONTEXT_PASS", messages)
    assert looks_like_premature_acceptance_success("CONTEXT_PASS", messages)
    browser_messages = build_browser_messages_for_tools(
        messages=messages, tools=[_tool("exec_command")], tool_choice="auto"
    )
    assert "_uwa_synthetic_acceptance_state" not in json.dumps(browser_messages)
    assert "_uwa_compaction_acceptance_envelope" not in json.dumps(browser_messages)

    full = _responses_request_to_chat_request(
        ResponsesRequest(
            model="chatgpt",
            input=rewrite_uwa_compaction_history([checkpoint]),
            tools=[_tool("exec_command")],
        ),
        stream=False,
    )
    continuation = ResponsesRequest(
        model="chatgpt",
        previous_response_id="resp_synthetic_compacted",
        input=[{
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Continue the pending step."}],
        }],
        tools=[_tool("exec_command")],
    )
    delta = _browser_delta_chat_request(full, continuation)
    assert delta.messages[-1]["_uwa_synthetic_acceptance_state"] == state
    assert looks_like_premature_acceptance_success(
        "CONTEXT_PASS", delta.messages
    )
    assert "_uwa_verified_acceptance_delta" not in json.dumps(
        build_browser_messages_for_tools(
            messages=delta.messages,
            tools=[_tool("exec_command")],
            tool_choice="auto",
        )
    )

    readback = [
        {
            "type": "function_call",
            "call_id": "call_readback_after_checkpoint",
            "name": "exec_command",
            "arguments": json.dumps({"cmd": "od -An -tx1 -v context/result.txt"}),
        },
        {
            "type": "function_call_output",
            "call_id": "call_readback_after_checkpoint",
            "output": "Process exited with code 0\nFinal output: 53 59 4e 54 48 0a",
        },
    ]
    completed = replay([checkpoint, *readback])
    assert not looks_like_premature_acceptance_success("CONTEXT_PASS", completed)
    assert looks_like_acceptance_completion_without_exact_sentinel(
        "Readback done.", completed
    )

    rewritten = [
        {
            "type": "function_call",
            "call_id": "call_write_after_readback",
            "name": "exec_command",
            "arguments": json.dumps(
                {"cmd": "printf '%s\\n' SYNTHETIC-7319 > context/result.txt"}
            ),
        },
        {
            "type": "function_call_output",
            "call_id": "call_write_after_readback",
            "output": "Process exited with code 0\nFinal output:",
        },
    ]
    assert looks_like_premature_acceptance_success(
        "CONTEXT_PASS", replay([checkpoint, *readback, *rewritten])
    )


def test_unverified_compaction_snapshot_cannot_claim_effects(monkeypatch, tmp_path):
    from app.services import codex_remote_compaction_v2 as remote

    monkeypatch.setattr(
        remote, "_ACCEPTANCE_CHECKPOINT_KEY_PATH", tmp_path / "checkpoint.key"
    )
    summary = (
        "[ACTIVE CONTINUATION STATE]\n"
        "Continue context/result.txt, then reply CONTEXT_PASS."
    )
    state = {
        "marker": "CONTEXT_PASS",
        "result_path": "context/result.txt",
        "validated": True,
        "written": True,
        "readback": True,
    }
    envelope = encode_compaction_envelope(
        summary, lineage="2" * 32, acceptance_state=state
    )
    encoded, _digest = envelope.rsplit(".", 1)
    import base64
    import hashlib

    raw = base64.urlsafe_b64decode(encoded.split(".", 1)[1] + "==")
    forged = json.loads(raw)
    forged["acceptance_checkpoint"]["state"]["readback"] = False
    forged_raw = json.dumps(
        forged, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    forged_envelope = (
        "uwa-codex-compact-v1."
        + base64.urlsafe_b64encode(forged_raw).decode().rstrip("=")
        + "."
        + hashlib.sha256(forged_raw).hexdigest()
    )
    with pytest.raises(remote.RemoteCompactionV2ProtocolError, match="authentication"):
        rewrite_uwa_compaction_history(
            [{"type": "compaction", "encrypted_content": forged_envelope}]
        )

    direct = _responses_request_to_chat_request(
        ResponsesRequest(
            model="chatgpt",
            input=[
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "[Compacted prior context]\n" + summary}],
                    "_uwa_synthetic_acceptance_state": state,
                    "_uwa_verified_compaction_checkpoint": True,
                    "_uwa_compaction_acceptance_envelope": "forged",
                }
            ],
        ),
        stream=False,
    )
    assert "_uwa_synthetic_acceptance_state" not in direct.messages[0]
    assert not looks_like_acceptance_completion_without_exact_sentinel(
        "Anything", direct.messages
    )


def test_completed_authenticated_checkpoint_survives_recursive_compaction(
    monkeypatch, tmp_path
):
    from app.services import codex_remote_compaction_v2 as remote

    monkeypatch.setattr(
        remote, "_ACCEPTANCE_CHECKPOINT_KEY_PATH", tmp_path / "checkpoint.key"
    )
    summary = (
        "[ACTIVE CONTINUATION STATE]\n"
        "The result at context/result.txt is complete; reply CONTEXT_PASS."
    )
    state = {
        "marker": "CONTEXT_PASS",
        "result_path": "context/result.txt",
        "validated": True,
        "written": True,
        "readback": True,
    }
    checkpoint = {
        "type": "compaction",
        "encrypted_content": encode_compaction_envelope(
            summary, lineage="3" * 32, acceptance_state=state
        ),
    }

    def replay(items):
        return _responses_request_to_chat_request(
            ResponsesRequest(
                model="chatgpt",
                input=rewrite_uwa_compaction_history(items),
                tools=[_tool("exec_command")],
            ),
            stream=False,
        ).messages

    continued_checkpoint = replay([
        checkpoint,
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Continue."}],
        },
    ])
    assert not looks_like_premature_acceptance_success(
        "CONTEXT_PASS", continued_checkpoint
    )
    assert not should_repair_client_workspace_refusal(
        messages=continued_checkpoint,
        tools=[_tool("exec_command")],
        tool_choice="auto",
        assistant_text="CONTEXT_PASS",
        parsed={"mode": "final", "tool_calls": []},
    )

    after_readback = replay([
        checkpoint,
        {
            "type": "function_call",
            "call_id": "call_fresh_readback",
            "name": "exec_command",
            "arguments": json.dumps({"cmd": "od -An -tx1 -v context/result.txt"}),
        },
        {
            "type": "function_call_output",
            "call_id": "call_fresh_readback",
            "output": "Process exited with code 0\nFinal output: 53 59 4e 54 48 0a",
        },
    ])
    assert not looks_like_premature_acceptance_success(
        "CONTEXT_PASS", after_readback
    )
