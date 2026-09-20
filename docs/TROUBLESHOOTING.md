# Troubleshooting and engineering decisions

This file is a fast index for recurring failure signatures. The detailed chronological record remains in [STANDALONE_S3_LIVE_GATE_2026-09-10.md](STANDALONE_S3_LIVE_GATE_2026-09-10.md).

## Browser/CDP unavailable

Symptoms:

```text
browser/CDP not connected
health reports browser unhealthy
```

Check the configured CDP port, default `9222`, and confirm the controlled Chromium-compatible browser is running with a usable logged-in ChatGPT Web tab.

Relevant code:

- `app/core/browser/connection.py`
- `app/services/chatgpt_web_surface.py`

## Wrong ChatGPT surface or dirty composer

Symptoms include Work surface, ambiguous target, stale text in the composer, authentication challenge, quota exhaustion, or an unexpected page.

The release harness fails closed before expensive compaction work.

Relevant code/tests:

- `app/services/chatgpt_web_surface.py`
- `app/services/chatgpt_web_prepare.py`
- `tests/test_chatgpt_web_surface*.py`

## `send_blocked_by_preexisting_generation`

A historical live failure occurred when the stream monitor and pre-send guard used different active-generation selectors. On a localized ChatGPT UI, one path could miss the Chinese Stop control and declare completion early.

Current design:

- shared selectors live in `app/core/generation_state.py`;
- `stream_monitor.py` and `executor_send.py` consume the same set.

Regression:

- `tests/test_stream_monitor_terminal_state.py`

Do not fix this class of failure by merely increasing the pre-send timeout before inspecting terminal-state detection.

## ChatGPT rate limiting

Symptoms:

```text
chatgpt_web_rate_limited
请求过于频繁
Too Many Requests
```

The bridge/gates must fail closed. The acceptance harness may dismiss an acknowledgement-only modal and apply bounded pacing, but it does not bypass account limits or automatically replay an uncertain request.

Relevant code:

- `app/services/chatgpt_web_rate_limit_guard.py`
- `tools/chatgpt_surface_preflight.py`
- `tools/standalone_s3_live_acceptance.py`

## HTTP 413 or oversized resumed history

Do not assume every broad-log 413 belongs to the currently failing probe. Inspect the exact phase JSONL first.

Conversation affinity and browser-delta construction intentionally avoid resending unnecessary full history when the verified Web conversation already contains it.

Relevant code/tests:

- `app/api/codex_responses_v2.py`
- `app/services/codex_web_session_affinity.py`
- `tests/test_codex_web_session_affinity.py`

## Model says `exec_command` is unavailable after a real tool ran

This is a contradiction when the current request declares the tool and prior client-tool evidence proves it executed.

Recursive compaction can remove the matching assistant function-call item while preserving a generated `[Function Call Output ...]` fallback. The bridge attaches private provenance to generated fallbacks so the policy can distinguish them from user-authored text.

Relevant code/tests:

- `app/api/codex_runtime.py`
- `app/services/client_tool_policy.py`
- `tests/test_client_tool_policy_repeated_refusal.py`

## Model asks the user to provide the task again after compaction

If `ACTIVE CONTINUATION STATE` already contains the unresolved workspace action, asking the user to resend the task is a recoverable contradiction.

Affinity deltas carry the newest compacted continuation as private bridge metadata on generated tool-result fallbacks. That metadata is not serialized into browser-visible prompt content.

Relevant code/tests:

- `app/api/codex_responses_v2.py`
- `app/services/client_tool_policy.py`
- `tests/test_codex_web_session_affinity.py`

## S4 candidate mismatch

If S4 reports a candidate SHA mismatch, do not edit the evidence file or weaken the check.

Regenerate the corresponding gate on the current exact HEAD:

- S3 result for S3 mismatch;
- Desktop verifier for Desktop mismatch;
- install smoke for install candidate mismatch.

## System Python cannot import `DrissionPage`

Release and acceptance tools must run with the project environment:

```bash
.venv/bin/python ...
```

Do not substitute system `python3` for browser-dependent acceptance commands unless that environment has the same dependencies.

## Repository becomes dirty during release acceptance

S3 and S4 expect a clean release tree. Do not edit tracked files while a candidate-bound gate is running.

Private evidence belongs under `~/.uwa`, not in the repository.

## Historical details

The long S3 record is retained because each unusual defensive rule has a real failure behind it. Use this troubleshooting index first, then open the matching dated section in [STANDALONE_S3_LIVE_GATE_2026-09-10.md](STANDALONE_S3_LIVE_GATE_2026-09-10.md) when deeper context is needed.


## `LARGE_CONTEXT_PASS` followed by `result_missing_trailing_newline`

A live S3 recovery once retained the correct large-context token and even returned
`LARGE_CONTEXT_PASS`, but wrote `large_context/result.txt` as the token bytes
without the required trailing newline.

This is not a context-loss failure. The retained token value was correct; the
local file-format contract was not.

Current protection:

- the final large-context prompt explicitly requires a newline-preserving write;
- it forbids newline-dropping forms such as `echo -n` and `printf '%s'`;
- it requires a separate byte-level readback proving the final byte is `0x0a`;
- plain `cat` output is explicitly insufficient because it does not prove a
  trailing newline;
- S3 classifies the mismatch precisely instead of reporting a generic token
  mismatch.

Relevant code/tests:

- `tools/codex_large_context_acceptance.py`
- `tools/standalone_s3_live_core.py`
- `tests/test_codex_large_context_acceptance.py`


## `send_blocked_by_preexisting_generation` after a completed seed/reply

A live S3 run on 2026-09-20 exposed a terminal-state race: Codex had already
received the exact `LARGE_CONTEXT_READY` reply and emitted `turn.completed`,
but two minutes later the next coarse turn found the ChatGPT page still showing
an active generation/Stop state. The pre-send guard correctly refused to submit
and eventually failed with `send_blocked_by_preexisting_generation`.

This means the earlier stream completion was unsafe even though the later guard
worked correctly.

Current protection:

- `GeneratingStatusCache` still uses the shared stable generation selectors;
- ChatGPT also gets a composer-scoped metadata fallback for Stop/Cancel/Abort
  controls when the UI does not expose a stable stop selector;
- the final settle phase now re-validates generation state continuously;
- if generation reappears during final settle, the prior stability window is
  discarded;
- generation must clear and remain clear for a fresh settle window;
- if generation remains active through the bounded final-settle grace, the turn
  fails instead of being released as completed;
- pre-send timeout logs include the detector source for future diagnosis.

Relevant code/tests:

- `app/core/generation_state.py`
- `app/core/stream_monitor.py`
- `app/core/workflow/executor_send.py`
- `tests/test_stream_monitor_terminal_state.py`


## Post-compaction final says declared client tools are not exposed

A live S3 recovery retained the correct durable token and successfully executed
multiple real `exec_command` calls, then recursive compaction removed the
immediately preceding function-call/output history. The next final response
incorrectly claimed that the current environment did not expose
`exec_command` or `write_stdin`.

Wire metadata proved that the request still declared both client tools. The
failure was therefore a policy/provenance gap after lossy compaction, not a real
tool-availability change.

Current protection:

- a final claim that an explicitly declared workspace tool is unavailable,
  missing, not exposed, or not callable is repaired directly from the current
  request's authoritative tool schema;
- this repair no longer depends on prior function-call history surviving
  recursive compaction;
- `tool_choice="none"` still disables the repair;
- the bridge still never executes a command itself and never bypasses Codex
  sandbox or approval behavior.

Relevant code/tests:

- `app/services/client_tool_policy.py`
- `tests/test_client_tool_policy_repeated_refusal.py`


## Post-compaction reply says no new concrete task

A live S3 recovery can retain the durable token and successfully execute the
workspace-validation `exec_command`, then return a text-only acknowledgement
such as:

```text
已接收当前上下文。可继续使用的精确测试值为 <token>。
当前消息没有包含新的具体执行任务。
```

This is a contradiction when the bridge still carries authoritative private
compacted continuation state saying that the result file must be written and
verified.

The client-tool policy now treats this wording as a missing-task clarification
only when compacted workspace intent/provenance is present. Ordinary chat
messages that happen to say there is no new task are not turned into tool calls.

Relevant regression coverage:

- `tests/test_client_tool_policy_repeated_refusal.py`
