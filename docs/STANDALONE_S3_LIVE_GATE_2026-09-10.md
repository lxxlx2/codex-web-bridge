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


## 2026-09-18 Recursive-compaction workspace continuation follow-up

The next S3 retry on `240904e5d39b4b66e29f2b54bfcddf1c3237b545` advanced past XML validation and successfully executed the post-compaction workspace-validation command. The retained exact token also survived recursive compaction. The remaining failure was:

```text
FAILURE_CLASS=post_compaction_recovery
FAILURE_DETAIL=final_reply_mismatch
```

Private trace evidence showed one successful `exec_command`:

```text
pwd && test -f .uwa_codex_acceptance && test -d large_context
```

and the final web reply correctly remembered `ORBIT-5921` plus the still-pending requirement to write and read back `large_context/result.txt`, but then falsely claimed that the current ChatGPT session did not have `exec_command`. No result file was created.

The root cause was the compacted-workspace repair predicate. It only recognized compacted workspace intent when the newest user-shaped message was a function-output fallback. A recursive compaction can occur after the first successful client tool call and before the remaining write/read steps, leaving the durable assistant compaction state plus a normal continuation user item. In that shape, the false tool-unavailable claim escaped specialized repair.

The policy now treats the newest structured `[ACTIVE CONTINUATION STATE]` as durable unresolved workspace intent even when the latest user item is not a function-output fallback. Focused repair prompts also carry the bounded compacted continuation state so exact values and pending file operations remain available during the repair sub-round. Regression coverage includes the exact recursive-compaction refusal pattern and verifies completed-only compacted history does not force a workspace repair.

This changes the release candidate SHA again. Exact-SHA Desktop E2E / S3 / install-smoke / S4 evidence must be regenerated after validation.


## 2026-09-19 Exact recursive-compaction refusal wording follow-up

The S3 retry on `7bfe6947614fe1a7ba69e2a6a78846e9d247b17e` again reached post-compaction recovery with one successful workspace-validation `exec_command`, exact recovery of `ORBIT-5921`, and no result file. The final web reply explicitly preserved the pending file-write/read task but used a live refusal shape that the compacted-workspace policy still did not classify:

```text
无法把其中声明的 exec_command / write_stdin 变成我当前会话实际可调用的客户端工具
...
我当前没有那个本地 Codex adapter 的 exec_command 执行入口
```

No client-workspace repair log appeared after the recursive compaction, confirming the previous continuation-state fix was reached but the final refusal wording escaped the refusal detector.

The refusal policy now covers this current-session / actual-callable / execution-entry wording while remaining limited to declared workspace client tools and unresolved compacted workspace intent. Exact live wording regression coverage verifies both direct detection and conversion into a repaired `exec_command` call.

This changes the release candidate SHA again. Exact-SHA Desktop E2E / S3 / install-smoke / S4 evidence must be regenerated after validation.


## 2026-09-19 Fine-to-arm boundary calibration

The S3 run on `dcfa6b5a8a5814e9d85f7d454747f9463c27ae2d` did not reach post-compaction recovery. The remote compaction probe advanced cleanly through coarse rounds and fine round 8:

```text
ACTIVE_LAST_TOKENS=72221
MARGIN_TO_TRIGGER=929
previous fine step ~= 858
```

The probe then sent another fixed fine filler. That turn failed before emitting a usage snapshot, producing:

```text
RUN_FAIL fine_usage_missing round=9
```

The prior arm-switch predicate only switched when `margin <= previous_fine_step` or the fixed 512-token guard. At 929/858 it therefore attempted another ~858-token fine step with only ~71 tokens of expected residual headroom before the configured hard-context trigger. This is too narrow for live variation and can fail before a normal completed-turn usage event.

The probe now switches to tiny arm turns when the remaining margin is within one observed fine step plus the fixed arm guard. This is a live-gate calibration change only; runtime compaction behavior is unchanged. Regression coverage includes the exact observed 929/858 boundary.

This changes the exact release-candidate SHA again. Exact-SHA S3 and downstream release evidence must be regenerated after validation.


## 2026-09-19 Restart/resume required-tool repair exhaustion

The S3 run on `dc3f78ce930ed9d80ac8cc89a047c4419971ceff` failed before the compaction probe during restart continuity:

```text
FAILURE_CLASS=restart_resume
FAILURE_DETAIL=rc=1
```

Private restart evidence showed the seed turn completed exactly with `CONTEXT_READY`, preserved the same thread id, and the resume request explicitly required `exec_command`. The web model returned two consecutive false client-tool-unavailable replies. Both were detected by the specialized workspace repair path, but the configured two repair retries were exhausted before any function call was emitted:

```text
STRICT_ATTEMPT=1  required_tool=exec_command  satisfied=false
STRICT_ATTEMPT=2  response_status=failed
tool_call_validation_exhausted: client_workspace_tool_refusal
```

The repair contract is now stronger for an explicitly required workspace tool. It explains that a valid `adapter_calls` envelope is the real transport consumed by the local client, forbids further capability commentary on repeated refusal, and requires a single tool-call-only response using the operation from the original request. A specifically required workspace tool also receives one narrow additional focused-repair attempt; generic tool validation retry limits are unchanged.

Regression coverage reproduces the restart workspace-guard command and verifies that two refusals can recover on the extra required-workspace attempt while repeated refusals still fail closed.

This changes the exact release-candidate SHA again. Exact-SHA S3 and downstream release evidence must be regenerated after validation.


## 2026-09-19 Adaptive fine-to-arm transition

The S3 run on `9c733f79be70f7754d6b164c26fd9421d9ab64f0` confirmed the earlier fine-to-arm safety fix but exposed a request-efficiency problem. The probe switched safely with:

```text
MARGIN_TO_TRIGGER=871
PREVIOUS_FINE_STEP=858
```

and then completed eight tiny arm turns. Each arm turn advanced only 47-48 tokens, leaving:

```text
PHASE=ARM ROUND=16 ... MARGIN_TO_TRIGGER=489
THRESHOLD_CROSSED=NO
RUN_FAIL threshold_not_reached
```

A prior run also reached account-side rate limiting while consuming many tiny arm turns. Increasing the arm-round cap would therefore increase web-request pressure without addressing the underlying calibration.

The probe now performs at most one adaptive medium transition filler before tiny arm turns. It estimates the filler size from the last measured fine-step slope and preserves a 256-token cushion before the trigger boundary. For the observed 871/858 case, this selects roughly 1.4 KiB instead of another 2 KiB fine filler, after which only a small number of arm turns should remain.

Runtime compaction behavior is unchanged; this is acceptance-probe calibration only. Regression coverage includes the exact 871/858 live boundary, the small-margin skip case, and transition prompt bounds.

This changes the exact release-candidate SHA again. Exact-SHA S3 and downstream release evidence must be regenerated after validation.


## 2026-09-19 Full-history resume affinity / HTTP 413

The S3 run on `8763aaba444a90acff8fce268682eeac3e7b580d` validated the adaptive transition calibration:

```text
PHASE=FINE ARM_SWITCH=YES MARGIN_TO_TRIGGER=929 PREVIOUS_FINE_STEP=858
PHASE=TRANSITION ROUND=09 ACK_EXACT=YES TARGET_BYTES=1606
ACTIVE_LAST_TOKENS=72908 STEP_TOKENS=687 MARGIN_TO_TRIGGER=242
PHASE=ARM ROUND=12 ... MARGIN_TO_TRIGGER=99
```

The next arm turn failed before usage was emitted:

```text
RUN_FAIL arm_usage_missing round=13
turn.failed: ChatGPT Web completed without an assistant message or client function call
```

The browser log exposed the real backing failure as HTTP 413, "message too long". The same evidence also showed that ordinary `codex exec resume` probe turns were repeatedly sent with:

```text
web_session_reused=False browser_input=full
```

The Codex CLI full-history resume shape does not necessarily carry a `previous_response_id`, so response-id-only affinity could not recognize that each request strictly extended the already-open ChatGPT conversation. The bridge therefore created/replayed full reconstructed history on every probe turn until the Web message-size limit was reached.

The bridge now maintains a second, hash-only history-lineage affinity. After a successful browser round it stores only a SHA-256 digest, message count, validated ChatGPT pathname, model/reasoning identity, and timestamp. When a later no-`previous_response_id` request strictly extends that exact history prefix, the bridge restores the same ChatGPT conversation and sends only the unrepresented suffix. No conversation text is retained by the affinity table. Compacted histories that no longer extend the prior lineage fail closed to the existing fresh-chat/full-history path, allowing a new compacted lineage to be established.

Regression coverage verifies strict-prefix matching, unrelated-history rejection, hash-only storage, suffix construction, and no-`previous_response_id` preparation reuse.

This changes the exact release-candidate SHA again. Exact-SHA S3 and downstream release evidence must be regenerated after validation.


## 2026-09-19 Post-compaction missing-task clarification

The S3 run on `bea1926c204d077796b2c1319ae437ca384b8790` passed release preflight, browser surface preflight, repo preflight, standalone listener readiness, local gates, restart continuity, and the remote compaction probe. This is the first run after the full-history affinity fix to reach post-compaction recovery again.

The remaining failure was:

```text
FAILURE_CLASS=post_compaction_recovery
FAILURE_DETAIL=final_reply_mismatch
```

The visible final Web reply was:

```text
请继续发送这一轮需要我执行的具体任务或验证步骤。
```

This is a distinct continuation failure from the earlier false "exec_command unavailable" replies. The model no longer denies the client tool; it asks the user to restate a task that is already present in the structured `[ACTIVE CONTINUATION STATE]`.

The client workspace policy now treats this narrow clarification shape as repairable only when a compacted unresolved workspace continuation is present. The repair prompt explicitly states that the pending task and verification steps are already recorded in the compacted continuation state and directs the model to execute the next unfinished workspace step instead of asking the user again. Ordinary clarification replies without compacted workspace state are not forced into tool calls.

Regression coverage uses the exact live Chinese reply, verifies conversion into an `exec_command` call with the preserved exact token/file target, and verifies the non-compacted negative case.

This changes the exact release-candidate SHA again. Exact-SHA S3 and downstream release evidence must be regenerated after validation.


## 2026-09-19 False workspace-mismatch sentinel after successful validation

The S3 run on `6f9e4fd49d2378c33dac0e665c257e450ead547d` again passed the remote compaction probe and reached post-compaction recovery. The private trace proved the complete required validation command executed successfully:

```text
COMMAND_1:
pwd && test -f .uwa_codex_acceptance && test -d large_context
EXIT_CODE=0
OUTPUT=/Users/jerson/uwa-codex-acceptance

COMMAND_2:
pwd && ls -la large_context
EXIT_CODE=0
```

The acceptance workspace independently confirmed both `.uwa_codex_acceptance` and `large_context` were present and the exact validation command returned 0. Nevertheless the final Web reply was:

```text
ACCEPTANCE_WORKSPACE_MISMATCH
```

and no `large_context/result.txt` was created.

This is a post-tool interpretation error. The final acceptance prompt allows the mismatch sentinel only when the complete validation command exits non-zero, so returning it after a real exit-code-0 result directly contradicts authoritative client-tool evidence.

The client workspace policy now repairs this exact contradiction only when history contains a real successful `exec_command` whose command includes the full acceptance validation fragments and whose corresponding tool result reports exit code 0. A genuine non-zero validation result remains untouched. The repair directs the model to continue the pending post-validation workspace steps from compacted state instead of reinterpreting validation.

Regression coverage reproduces the successful validation plus extra directory inspection observed live, verifies recovery into the pending result-file write, and verifies an exit-code-1 validation does not trigger repair.

This changes the exact release-candidate SHA again. Exact-SHA S3 and downstream release evidence must be regenerated after validation.


## 2026-09-19 Stale rate-limit acknowledgement dialog

After an S3 run was interrupted by a genuine ChatGPT Web rate-limit event, the
account later became usable again, but the controlled browser tab still had the
old acknowledgement-only rate-limit dialog open. The standalone surface probe
continued to classify the tab as:

```text
blocking_reason=rate_limited
failure_class=chatgpt_web_rate_limited
```

even though the stale dialog itself was the remaining blocker.

The preflight tool previously detected rate-limit dialogs but intentionally
never dismissed them. It now performs one narrow cleanup action: when the
surface is classified as `rate_limited`, it may physically click exactly one
acknowledgement-only button (`Got it`, `OK`, `Okay`, `明白了`, or
`知道了`) inside exactly one visible rate-limit dialog. It never clicks
`Retry`, never dismisses quota/usage-exhaustion blockers, and never sends a
message. The surface is then re-probed. If the rate-limit blocker remains or
reappears, preflight still fails closed as `chatgpt_web_rate_limited`.

Regression coverage verifies stale-dialog recovery, persistent-limit
fail-closed behavior, and no click when a unique acknowledgement target cannot
be proven.

This changes the exact release-candidate SHA again. Exact-SHA S3 and downstream
release evidence must be regenerated after validation.


## 2026-09-19 Rate-limit cooldown after acknowledgement dismissal

The S3 run on `0a96fe095444627d0428e2c587398bc07cd90f1a`
demonstrated that stale-notice dismissal alone is not sufficient evidence that
the account-side request limiter has reset. Preflight successfully performed:

```text
actions=["dismiss_rate_limit_notice", "new_chat"]
blocking_reason=none
```

and an immediate S3 run then reached a new genuine rate-limit event during the
restart/resume phase:

```text
FAILURE_CLASS=restart_resume
FAILURE_DETAIL=rc=1
FAILURE_CLASS=chatgpt_web_rate_limited
FAILURE_DETAIL=rate_limited
```

The S3 wrapper now preserves the `dismiss_rate_limit_notice` action from
surface normalization and, when observed, enforces a quiet cooldown before any
live acceptance traffic is sent. The default is 180 seconds, configurable with
`UWA_S3_RATE_LIMIT_COOLDOWN_SEC` and bounded to 0-900 seconds. After the quiet
period, the wrapper performs another passive surface recheck and still fails
closed if a blocker is visible.

This does not bypass rate limiting and does not retry through an active
limiter. It only prevents the acceptance runner from immediately re-entering a
request-heavy sequence after acknowledging a recent rate-limit notice.

This changes the exact release-candidate SHA again. Exact-SHA S3 and downstream
release evidence must be regenerated after validation.


## 2026-09-19 Compaction-probe cooldown before recovery

The S3 run on `901be27a8f644d89aa12807096774204a4617b10`
started from a clean surface and passed restart continuity. The request-heavy
auto-compaction probe reached the visible success marker:

```text
AUTO_COMPACT_TRIGGER_OK
```

and then ChatGPT Web raised a new genuine "requests too frequent" dialog before
the post-compaction recovery could complete. The outer gate reported:

```text
FAILURE_CLASS=post_compaction_recovery
FAILURE_DETAIL=codex_turn_runtime_error
FAILURE_CLASS=chatgpt_web_rate_limited
FAILURE_DETAIL=rate_limited
```

This shows the earlier cooldown after *stale-dialog dismissal* solves only the
startup case. A clean startup can still accumulate enough request pressure
inside the compaction probe to enter the limiter immediately before the final
recovery turn.

The S3 core now enforces a second quiet period after the remote compaction probe
has fully passed and before sending the post-compaction recovery request. The
default is 180 seconds, configurable with
`UWA_S3_COMPACTION_COOLDOWN_SEC` and bounded to 0-900 seconds. After waiting,
the runner performs an in-place surface cleanup that may dismiss exactly one
acknowledgement-only stale rate-limit notice without navigating away from the
current ChatGPT conversation. If the blocker remains, the gate fails closed.

This preserves the exact Web conversation required for same-thread recovery and
prevents the successful trigger probe from immediately consuming another
request inside the same account-side rate-limit window.

This changes the exact release-candidate SHA again. Exact-SHA S3 and downstream
release evidence must be regenerated after validation.


## 2026-09-19 Burst limiter after first restart seed

The S3 run on `778544286eb0b3ed6e767a2ec2f0ac23b9b82a39`
started from a clean surface and reached the first restart seed response:

```text
CONTEXT_READY
```

The next resume request was then blocked almost immediately by a fresh ChatGPT
Web "requests too frequent" dialog, and the outer gate reported
`chatgpt_web_rate_limited`.

This establishes two separate limiter behaviors:

1. A fresh target can hide a limiter that was triggered by a prior S3 run, so
   stale-dialog detection alone is insufficient across runs.
2. Even inside one clean run, back-to-back live acceptance turns can form a
   burst that triggers the account-side limiter.

The S3 wrapper now persists only a timestamp/class marker for the latest
`chatgpt_web_rate_limited` failure. A subsequent run honors the remaining
180-second quiet window even if target reset removed the old dialog. The S3
core also enforces a default 30-second minimum gap between completed live Codex
turns, including restart seed/resume and every compaction-probe round. This is
acceptance-only pacing; runtime request behavior is unchanged.

The cross-run quiet window is configurable with
`UWA_S3_RECENT_RATE_LIMIT_COOLDOWN_SEC` (0-900 seconds). Per-turn pacing is
configurable with `UWA_S3_MIN_LIVE_TURN_GAP_SEC` (0-120 seconds).

This changes the exact release-candidate SHA again. Exact-SHA S3 and downstream
release evidence must be regenerated after validation.


## 2026-09-19 Wait before target reset while rate-limited

The S3 run on `b0917e5024f85ab0ddc035b59dc82948fb03ae58`
still hit a fresh Web rate-limit immediately after the first restart seed even
with a 30-second inter-turn gap:

```text
CONTEXT_READY
S3_INTER_TURN_COOLDOWN_SEC=28.4
FAILURE_CLASS=restart_resume
FAILURE_CLASS=chatgpt_web_rate_limited
```

The visible limiter text refers to temporary access to conversation history,
not only model-generation quota. This means browser target reset/navigation can
also be part of the pressure while an account is still inside a recent limiter
window.

The cross-run rate-limit wait therefore now happens before the runner closes,
opens, or navigates any ChatGPT Web target. A recent limiter marker acts as a
circuit breaker around all acceptance browser activity, not just model turns.
After that quiet window expires, normal fresh-target normalization proceeds.

This matches standard rate-limit practice: stop issuing requests during the
cooldown window rather than continuing with "harmless" setup traffic.

This changes the exact release-candidate SHA again. Exact-SHA S3 and downstream
release evidence must be regenerated after validation.

## Gate state

```text
S1 dependency / import / runtime audit       PASS / CLOSED
S2 extraction / decoupling / minimal tree    PASS / CLOSED
S3 CI + CLI/Desktop/live parity              CURRENT / LIVE RUN READY
S4 release candidate / first release         PENDING
```

S3 must remain open until the standalone live runner completes successfully. No release tag is created before that result is recorded and the S4 release-candidate checks are prepared.
