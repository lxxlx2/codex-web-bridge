# Standalone S3 live parity gate

Date: 2026-09-10

S1 and S2 are closed. S3 now has a one-shot live acceptance runner for the standalone repository itself:

```text
tools/standalone_s3_live_acceptance.py
```

The runner is intentionally fail-closed. It does not switch to the official Codex provider, does not commit or push, and stores raw Codex JSONL plus private thread identifiers only under `~/.uwa/standalone-s3/` with private permissions. Terminal output is limited to sanitized gate state.

## What the runner proves

The single run covers the release-plan requirements that need a real local environment:

- current clean `standalone-dev` checkout on macOS;
- exact configured route `provider=uwa`, `model=chatgpt`, reasoning effort `high`;
- listener ownership by the standalone checkout, including a controlled migration from the known integrated `lxxlx2/universal-web-api` checkout if it currently owns port 8199;
- standalone health and browser connection with `running_count=0` before live work;
- public-repository safety check, dependency audit and focused local regressions including stream cancellation cleanup;
- a real Codex CLI turn using the client-side `exec_command` tool;
- same-thread continuation after restarting the standalone listener;
- native auto-compaction trigger evidence;
- remote V2 compaction completion evidence;
- post-compaction same-thread recovery with a real local `exec_command` effect;
- metadata route audit proving UWA / chatgpt / high on the actual wire activity;
- request-manager cleanup to `running_count=0`;
- repository cleanliness after the live run.

The synthetic acceptance workspace is separate from the standalone source checkout. The runner does not use private source code, command bodies, prompt text or tool output as public evidence.

## CI checkpoint before live execution

The S3 runner was added in `9cbd19b89a3e8e7767f06e213e4bd368dadc2a80`, and its focused non-live coverage was added in `c136040ffb6f0f56662928fa3af9fd3472ffda6c`.

Standalone CI run 204 completed successfully on `c136040ffb6f0f56662928fa3af9fd3472ffda6c`:

```text
scaffold         PASS
runtime-import   PASS
codex-regression PASS
```

The broad Codex regression job discovers `tests/test_codex*.py`, so `tests/test_codex_standalone_s3_runner.py` is part of that green checkpoint.

## One-shot local command

From a current standalone checkout:

```bash
cd "$HOME/codex-web-bridge"
git switch standalone-dev
git pull --ff-only
python3 tools/standalone_s3_live_acceptance.py
```

If the repository has not yet been cloned locally, clone it first and then run the same acceptance command from `standalone-dev`.

The runner requires a real installed Codex CLI and the existing logged-in ChatGPT browser environment used by the bridge. It will create or reuse the standalone Python environment through the normal lifecycle path.

## PASS contract

A fully successful run ends with the following sanitized markers:

```text
S3_REPO_PREFLIGHT=PASS
S3_LOCAL_SAFETY_REGRESSION=PASS
S3_UWA_HEALTH=PASS
S3_REAL_CLIENT_TOOL=PASS
S3_SAME_THREAD_RESTART_RECOVERY=PASS
S3_NATIVE_AUTO_COMPACTION=PASS
S3_REMOTE_V2_COMPACTION=PASS
S3_POST_COMPACTION_RECOVERY=PASS
S3_ROUTE_UWA_CHATGPT_HIGH=PASS
S3_REQUEST_MANAGER_CLEAN=PASS
S3_REPOSITORY_CLEAN_AFTER_LIVE=PASS
STANDALONE_S3=PASS_LIVE_CLOSED
```

Any mismatch stops the run and prints only `FAILURE_CLASS` plus a sanitized detail. Raw evidence remains private under `~/.uwa/standalone-s3/`.

## 2026-09-18 Desktop required-tool and send-state follow-up

Live Desktop evidence on `standalone-dev` proved the specifically required client-tool path can recover from an initial Web refusal:

```text
REQUIRED_TOOL='exec_command'
STRICT_ATTEMPT=1  FUNCTION_CALL_NAMES=[]             REQUIRED_TOOL_SATISFIED=False
STRICT_ATTEMPT=2  FUNCTION_CALL_NAMES=['exec_command'] REQUIRED_TOOL_SATISFIED=True
final continuation completed after function_call_output
```

The next targeted CDATA live probe exposed a separate browser-workflow failure. The prompt was filled, but the ChatGPT page was still classified as a pre-existing generation state. The send guard correctly refused to submit and raised `send_blocked_by_preexisting_generation`, but the workflow layer did not classify that code as terminal. A network monitor therefore remained alive until RequestManager's 600-second zombie sweep cancelled the request. Private evidence recorded:

```text
[SEND] wait for pre-existing generation -> timeout=120s
send_blocked_by_preexisting_generation
request remained RUNNING
zombie_timeout after about 614s
surface blocker after failure: composer_not_empty
```

Follow-up fixes:

- `ee6414c3` makes blocked/undispatched sends re-raise directly from the step layer.
- `0b7e18f9` classifies blocked/undispatched sends as terminal workflow errors so cleanup can run immediately.
- `1088b986` adds regression coverage for the terminal send-state classification.

Current live candidate after those fixes:

```text
1088b986fb61cfe65d25380d6027d6cf3235eb84
```

S3 remains open. The new candidate still requires local regression and a repeated Desktop live probe before the CDATA case can be considered closed.

## 2026-09-18 Desktop E2E cancelled-helper composer follow-up

The first exact-candidate Desktop E2E retry on `9e9cff581fbcce7285ee1a2ebabfad0d7b70ebd0` exposed a separate cancellation cleanup race.

Step 1 completed and bound a ChatGPT conversation. Before Step 2, a helper request using the same controlled browser tab started a fresh ChatGPT turn, filled the composer, and was cancelled before dispatch. The browser workflow observed cancellation only after `FILL_INPUT` completed, so the helper-owned prompt remained in the shared composer. Step 2 then failed closed during fresh-turn preparation with:

```text
chatgpt_web_composer_not_empty: blocking_reason=composer_not_empty
```

Private wire evidence also showed the operator Step 2 request itself had not reached a real `exec_command`; the dirty composer was created by the cancelled helper workflow.

The runtime fix now calls the existing ownership-checked unsent-composer rollback from `cleanup_after_workflow()`. It only clears an exact normalized hash match owned by that executor, refuses attachment/user-modified composers, and does nothing once a real send action has been dispatched. Focused regressions cover both cancellation cleanup and post-dispatch preservation.

Because this changes the candidate SHA, all release-bound Desktop E2E / S3 / install-smoke / S4 evidence must be regenerated on the new HEAD.


## 2026-09-18 Post-compaction quoted-protocol false positive

The next exact-candidate S3 run reached post-compaction recovery and failed after the web model refused the required client tool. Private evidence showed the final validation summary:

```text
The reply looked like an XML-style tool call, but it could not be parsed into a valid declared tool.
```

There was no matching `XML tool-call parse rejected` structural log entry. The visible web reply explained that it could not fabricate `<adapter_calls>`, with the protocol tag shown as Markdown inline code. This exposed a validation/parser inconsistency:

- the XML parser masks inline and fenced Markdown code before looking for executable tool envelopes;
- malformed-tool detection scanned the raw text and therefore treated the quoted `<adapter_calls>` protocol name as a real malformed tool-call candidate.

The validator now reuses the parser's ignored-markup masking before XML-like detection. Regression coverage proves that inline/fenced protocol examples are ignored while unquoted protocol markup is still treated as a malformed candidate. All actual XML parsing and declared-tool/schema validation remain fail-closed.

This changes the release candidate SHA again. Desktop E2E evidence on `105bc97adb21786a4a312875f0c1dda028f9e137` remains historical capability evidence only; exact-SHA Desktop E2E / S3 / install-smoke / S4 evidence must be regenerated after the new fix is validated.

## Gate state

```text
S1 dependency / import / runtime audit       PASS / CLOSED
S2 extraction / decoupling / minimal tree    PASS / CLOSED
S3 CI + CLI/Desktop/live parity              CURRENT / LIVE RUN READY
S4 release candidate / first release         PENDING
```

S3 must remain open until the standalone live runner completes successfully. No release tag is created before that result is recorded and the S4 release-candidate checks are prepared.
