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


## 2026-09-19 Adaptive Web rate-limit circuit breaker

The first S3 run on `b0917e5024f85ab0ddc035b59dc82948fb03ae58`
still hit a fresh Web limiter immediately after `CONTEXT_READY`, even though
the second live turn was delayed by about 28 seconds. The prior run that had
triggered the limiter predated persistent rate-limit markers, so this first
post-change run had no cross-run cooldown state to honor.

The fixed-delay approach was also too weak as a general strategy. OpenAI's
published guidance for temporary rate limits recommends honoring an explicit
retry delay when available and otherwise using exponential backoff rather than
repeated fixed-delay retries. The S3 wrapper now follows that pattern as closely
as the Web UI permits:

- rate-limit state is honored before any ChatGPT target reset/navigation;
- repeated rate-limit failures within one hour increment a small persistent
  streak counter;
- cross-run cooldown grows exponentially from 180 seconds and is capped at
  900 seconds;
- after any recent rate-limit marker, the next recovery run raises the
  acceptance-only minimum live-turn gap to at least 60 seconds;
- the existing post-compaction 180-second quiet window remains in place.

The marker stores only timestamp, failure class, and streak count. No
conversation content is persisted.

This changes the exact release-candidate SHA again. Exact-SHA S3 and downstream
release evidence must be regenerated after validation.


## 2026-09-19 False restart-continuity workspace mismatch

The S3 run on `634b3dbba1255a5d078fed60e252a037f44f307c`
reached restart continuity without a rate-limit failure. The restart resume trace
showed the exact required validation command completed successfully:

```text
pwd && test -f .uwa_codex_acceptance && test -d context
EXIT_CODE=0
OUTPUT=/Users/jerson/uwa-codex-acceptance
```

The acceptance workspace independently confirmed both the marker and `context`
directory were present and the same command returned 0. Nevertheless the Web
reply was:

```text
ACCEPTANCE_WORKSPACE_MISMATCH
```

and `context/result.txt` was never created.

The existing false-mismatch repair was intentionally narrow but only recognized
the post-compaction `large_context` validation command. The restart-continuity
gate uses the same acceptance sentinel contract with `context`, so the repair
did not fire.

The detector now recognizes either canonical acceptance workspace validation:
`large_context` for post-compaction recovery or `context` for restart
continuity, while still requiring the acceptance marker and an authoritative
exit-code-0 client tool result. Real nonzero validation results remain untouched.
The repair instruction now refers to the current acceptance request or compacted
continuation state so it is correct for both paths.

This changes the exact release-candidate SHA again. Exact-SHA S3 and downstream
release evidence must be regenerated after validation.


## 2026-09-19 Post-compaction readback toolset refusal

The S3 run on `2167f341961a97fa40dc8d3b8ae22c53114d3928`
passed restart continuity and the compaction cooldown, then reached the final
post-compaction recovery sequence. The live Web state showed that the
`large_context/result.txt` write step had already completed and only the real
readback remained. The model then replied:

```text
无法执行该 exec_command 调用，因为当前实际可用工具集中没有这个客户端工具。
我不能伪造 <adapter_calls> 并将其当作已执行结果。
```

This is a post-tool contradiction: the same conversation already contains a
successful client `exec_command` call/result, so claiming that the current
toolset has no such client tool is invalid. The existing post-tool refusal
patterns covered unavailable/exposed wording and readback-specific refusals,
but did not match this exact word order where `exec_command` appears before
"当前实际可用工具集中没有这个客户端工具".

The post-tool detector now covers this current-toolset-absent wording. The
repair remains gated on actual prior workspace-tool history, so ordinary
capability statements without a real prior client tool call are unaffected.
Regression coverage reproduces the exact live Chinese refusal and verifies
recovery into a real `exec_command` readback of
`large_context/result.txt`.

This changes the exact release-candidate SHA again. Exact-SHA S3 and downstream
release evidence must be regenerated after validation.


## 2026-09-19 Premature durable-state-only completion

The S3 run on `a950830b76d4fc7d3794e2e8c816e32d92deac36`
again passed restart continuity and compaction cooldown, then reached
post-compaction recovery. The Web model recovered the durable token correctly
but stopped with:

```text
当前上下文已恢复。需要继续保留的精确值是：ORBIT-5921。
```

This is a different continuation failure from tool unavailability. The model
successfully recovered durable exact state but treated that acknowledgement as
task completion even though `[ACTIVE CONTINUATION STATE]` still contained
unfinished client-workspace actions.

The workspace repair policy now recognizes this narrow state-only completion
shape only when a compacted workspace continuation is present. It directs the
model to execute the next unfinished workspace step instead of restating the
recovered token. Ordinary requests that merely ask whether a value was
remembered remain unaffected.

Regression coverage uses the exact live Chinese reply, verifies conversion into
an `exec_command` continuation, and includes a non-compacted negative case.

This changes the exact release-candidate SHA again. Exact-SHA S3 and downstream
release evidence must be regenerated after validation.


## 2026-09-19 Pre-fill send lifecycle race in the compaction probe

The S3 run on `14058395248b1123447c2754bd95b0f3afe27cac`
passed restart continuity, entered the remote compaction probe, and completed
the seed contract:

```text
SEED_REPLY_EXACT=YES
SEED_TOOL_EFFECTS=0
PRIVATE_THREAD_CAPTURED=YES
```

The first coarse turn then failed. The probe originally surfaced this only as:

```text
RUN_FAIL coarse_usage_missing round=1
```

Private browser logs showed the real failure happened earlier in the send
lifecycle:

```text
[SEND] 发送前检测到页面仍处于旧生成/停止态，等待其结束后再提交本次消息 (timeout=120.0s)
[SEND] 等待旧生成态结束超时，本次发送动作尚未执行
send_blocked_by_preexisting_generation
```

At failure time the ChatGPT composer still contained about 29k characters from
the next coarse prompt. The prompt had already been written during
`FILL_INPUT`; only the later `CLICK` step waited for the preceding generation
to become idle. ChatGPT permits typing while an older answer is still
generating, so this ordering can strand a new prompt in the shared composer.

The browser workflow now performs the ChatGPT old-generation idle guard before
mutating `input_box` on the browser-composer path. Request-transport sends and
non-ChatGPT routes are unchanged. The normal click-time guard remains as a
second check. S3 additionally gives this pre-fill guard a 300-second timeout so
the high-reasoning live acceptance can wait longer without contaminating the
composer; normal runtime keeps the existing configured timeout unless explicitly
overridden.

The compaction probe also now reports nonzero turn return codes before checking
token usage, so a failed browser send is classified as a turn failure instead
of the secondary `*_usage_missing` symptom.

This changes the exact release-candidate SHA again. Exact-SHA S3 and downstream
release evidence must be regenerated after validation.


## 2026-09-19 Rate-limit guard wrapper signature regression

The S3 run on `c434e160fabe5be0c4e747f4c430819aa666eafe`
failed immediately in `restart_seed` before a message was sent. The private
trace recorded:

```text
stream disconnected before completion:
install_chatgpt_web_rate_limit_guard.<locals>.guarded_wait()
got an unexpected keyword argument 'wait_timeout_override'
```

The previous pre-fill lifecycle fix extended
`_wait_for_send_idle_before_action` with the optional
`wait_timeout_override` keyword. The ChatGPT Web rate-limit guard monkeypatch
still wrapped the old two-argument signature
`guarded_wait(self, send_selector)`, so the new S3 pre-fill call failed in the
wrapper before reaching the executor wait implementation.

The wrapper now forwards `*args, **kwargs` transparently after applying the
initial-send guard. Regression coverage installs the real wrapper around a fake
extended wait method and verifies that `wait_timeout_override=300.0` reaches
the wrapped method unchanged.

No release evidence from this failed SHA is reusable. Exact-SHA S3 and all
downstream release gates must be regenerated after validation.


## 2026-09-19 Release-metadata CI dependency closure

The exact S3 candidate `6e16543df85568b6fe2ce4fcd44012bd1eaae679`
closed the full live S3 gate:

```text
STANDALONE_S3=PASS_LIVE_CLOSED
```

Before collecting downstream Desktop/install/S4 evidence, the exact-SHA GitHub
Actions result was checked. `scaffold-static`, `runtime-import`, and
`codex-regression` were green, but `release-metadata` failed during test
collection with:

```text
ModuleNotFoundError: No module named 'DrissionPage'
```

The release-metadata job installed only `pytest`, while the current Desktop
release-gate test import graph reaches the standalone ChatGPT browser surface
modules and therefore requires the normal runtime dependencies. Other runtime
jobs already install `requirements.txt`.

The release-metadata job now installs `requirements.txt` before its focused
release-gate tests. This is CI dependency closure only; runtime behavior is
unchanged.

Because the workflow commit changes the candidate SHA, the successful S3 result
on `6e16543...` remains historical evidence and must be regenerated on the new
exact candidate before Desktop E2E, install smoke, S4, merge, or tagging.


## 2026-09-19 Final-candidate restart readback refusal

The candidate `8f9719f74fe8ccf3da01e023e4730ae6f41cbae3`
passed the local 493-test suite and entered the candidate-bound S3 run. The
restart seed succeeded, but restart resume ended with:

```text
无法继续完成验收：当前这一轮没有可调用的客户端 exec_command，
因此缺少对 context/result.txt 的最终读取确认，不能据此回复 CONTEXT_PASS。
```

This is another post-tool contradiction. The restart acceptance flow already
contains successful real `exec_command` call/result history, so a later claim
that "this round" has no callable client `exec_command` is invalid. The
existing post-tool detector covered current-session, current-environment, and
toolset-absent wording, but not the exact "当前这一轮没有可调用的客户端
exec_command" order.

The detector now covers this narrow wording only when a prior workspace client
tool call/result is present, and regression coverage reproduces the exact live
reply and verifies repair into the required `context/result.txt` readback.

This changes the exact candidate SHA again. The earlier
`6e16543...` S3 PASS remains historical; S3 and all downstream candidate-bound
release evidence must be regenerated on the new SHA.

## 2026-09-19 Active-generation text terminal-state race

The exact candidate `2b4deda4b1cce012a60ddc3c2eaa9ddd25376f73`
passed the targeted policy/S3 regressions and the full local suite:

```text
targeted: 75 passed
full suite: 495 passed
```

Its live S3 run also closed the previous restart-resume readback blocker:

```text
S3_PHASE=RESTART_CONTINUITY_PASS
```

The next remote-compaction seed completed its visible contract:

```text
SEED_REPLY_EXACT=YES
SEED_TOOL_EFFECTS=0
PRIVATE_THREAD_CAPTURED=YES
```

The first coarse turn then failed with:

```text
RUN_FAIL coarse_turn_failed round=1 rc=1
stream disconnected before completion: send_blocked_by_preexisting_generation
```

Private browser evidence showed the ChatGPT pre-fill idle guard detected the
preceding seed turn as still generating, waited the full S3-specific 300-second
window, and failed before mutating the composer. This proves the earlier
pre-fill ordering fix remained effective.

Source inspection identified the upstream lifecycle gap in
`app/core/stream_monitor.py`: the ordinary text stable-count and long-silence
completion branches could declare a turn terminal while
`still_generating=True`. A final-looking DOM reply could therefore be returned
to Codex while the same ChatGPT turn still exposed an active generation/stop
state.

The runtime now centralizes the ordinary-text terminal decision and requires the
active generation state to clear before either stable-text or long-silence
completion is accepted. The existing image/recovery branches remain outside
that helper and retain their specialized behavior. Focused regression coverage
proves active generation blocks both ordinary completion paths, idle generation
allows them, and non-text/suppressed paths are not claimed by the helper.

Implementation commits:

```text
f5e7cec  Require idle generation state for text completion
52c9425  Cover active-generation text completion invariant
```

Local validation of these new commits is pending. The full candidate-bound S3
run must not be repeated until the focused regression and repository full suite
pass. Because these changes move HEAD, all candidate-bound release evidence must
be regenerated on the final exact SHA after documentation is committed.


## 2026-09-19 Final Gate B post-tool readback refusal ordering

Frozen candidate `131abfd9cfe6d68ede3e3b34f195ad56ea8aa20f`
passed release/browser/repository/local preflight but failed the restart-resume
turn before `RESTART_CONTINUITY_PASS`:

```text
STANDALONE_S3=FAIL
FAILURE_CLASS=restart_resume
FAILURE_DETAIL=final_reply_mismatch
```

Private restart evidence showed the seed completed exactly with
`CONTEXT_READY`. The resume turn then executed two real client
`exec_command` calls: the acceptance workspace check and the write of the
durable context token to `context/result.txt`. The write succeeded and the
result file contained the expected token. The model then stopped with:

```text
无法完成所要求的本地 exec_command 读取校验，因此不能据实回复 CONTEXT_PASS。
```

The required third readback call was therefore missing.

The existing post-tool workspace repair already handled two equivalent readback
refusal orderings:

```text
exec_command -> cannot -> read/verify
cannot -> read/verify -> exec_command
```

This live wording used the uncovered ordering:

```text
cannot -> exec_command -> read/verify
```

The client-tool policy now recognizes that third ordering only inside the
existing post-tool contradiction path, where a real workspace client tool call
has already appeared. It repairs the final text back into the next real client
tool call instead of weakening required-tool duplicate suppression.

Focused regression coverage reproduces the exact live Chinese refusal and proves
that the roundtrip is repaired into another `exec_command` request for the
readback step.

Implementation commits:

```text
bacef19  Repair post-tool readback refusal ordering
6758b0d  Cover Gate B readback refusal wording
```

This runtime change invalidates candidate-bound evidence from
`131abfd9...`. After local validation, all exact-SHA live/release evidence must
be regenerated on the new candidate.


## Gate state

```text
S1 dependency / import / runtime audit       PASS / CLOSED
S2 extraction / decoupling / minimal tree    PASS / CLOSED
S3 CI + CLI/Desktop/live parity              CURRENT / LIVE RUN READY
S4 release candidate / first release         PENDING
```

S3 must remain open until the standalone live runner completes successfully. No release tag is created before that result is recorded and the S4 release-candidate checks are prepared.
