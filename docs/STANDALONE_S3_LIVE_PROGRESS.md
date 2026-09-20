# Standalone S3 Live Progress Log

This branch records live S3 acceptance progress without moving the active
`standalone-dev` release-candidate SHA. Candidate-bound release evidence remains
valid only for the exact candidate commit named in each entry.

## 2026-09-19 candidate 2b4deda4b1cce012a60ddc3c2eaa9ddd25376f73

Local validation:

```text
targeted: 75 passed in 0.51s
full suite: 495 passed, 22 warnings in 15.03s
```

Live S3 reached:

```text
S3_PHASE=RELEASE_PREFLIGHT_PASS
S3_PHASE=ACCEPTANCE_TARGET_RESET
S3_PHASE=BROWSER_SURFACE_PREFLIGHT_PASS
S3_CHATGPT_SURFACE_PREFLIGHT=PASS
S3_PHASE=REPO_PREFLIGHT_PASS
S3_PHASE=UWA_ROUTE_CONFIGURED
S3_PHASE=STANDALONE_LISTENER_READY
S3_PHASE=LOCAL_GATES_PASS
S3_PHASE=RESTART_CONTINUITY_PASS
```

This closes the previous restart-resume readback blocker on the exact candidate.
The specialized repair for the false claim that the current turn had no callable
client `exec_command` was exercised successfully by the live restart continuity
gate.

Current blocker:

```text
STANDALONE_S3=FAIL
FAILURE_CLASS=remote_compaction_probe
FAILURE_DETAIL=rc=1
```

Sanitized remote-compaction probe evidence:

```text
CONTEXT_WINDOW=77000
AUTO_COMPACT_LIMIT=69300
HARD_CONTEXT_LIMIT=73150
AUTO_COMPACT_SCOPE=body_after_prefix
TRIGGER_TARGET_LIMIT=73150
COARSE_BYTES=46000
FINE_BYTES=2048
SEED_REPLY_EXACT=YES
SEED_TOOL_EFFECTS=0
PRIVATE_THREAD_CAPTURED=YES
RUN_FAIL coarse_turn_failed round=1 rc=1
```

The failure occurs after a successful large-context seed and before the first
coarse filler turn completes. The next diagnostic step is to inspect the private
`trigger-probe-01-coarse.jsonl` trace and matching UWA/browser log metadata to
identify the direct Codex/browser failure behind the nonzero return code. Do not
rerun the full S3 stress probe until that direct failure is classified.

A prior 2026-09-19 live incident also failed on the first coarse turn because the
ChatGPT composer was filled before an older generation had become idle. That
incident led to the pre-fill idle guard and extended S3 pre-fill timeout. The
current failure must be compared against its private trace before deciding
whether this is the same lifecycle class or a new failure.


### Direct failure classification

The private coarse-turn trace confirms the direct failure:

```text
stream disconnected before completion: send_blocked_by_preexisting_generation
turn.failed
```

The matching UWA log shows the first coarse request entered the ChatGPT
composer pre-fill idle guard at 21:24:17, detected an existing generation/stop
state, waited the full S3 override of 300 seconds, and failed at 21:29:17 before
mutating the input box:

```text
[SEND] 发送前检测到页面仍处于旧生成/停止态，等待其结束后再提交本次消息 (timeout=300.0s)
[SEND] 等待旧生成态结束超时，本次发送动作尚未执行
send_blocked_by_preexisting_generation
```

This proves the newer pre-fill ordering fix is working as intended: the coarse
prompt was not stranded in the composer. The remaining blocker is that the
previous seed turn can leave the ChatGPT surface in a generation/stop state for
more than five minutes even after the visible exact reply
`LARGE_CONTEXT_READY` has already appeared.

The next implementation investigation should focus on terminal-state
reconciliation after a Web response becomes stable/exact. The bridge must not
start a new composer mutation while the old generation state remains live, but
the S3 path needs a safe way to distinguish a genuinely still-running response
from a stale UI generation state after the expected response is already stable.
No full S3 rerun should be performed until this lifecycle condition is handled
or a focused reproduction proves the state clears on its own.


### Source-level diagnosis

Inspection of `app/core/stream_monitor.py` found a matching completion hazard in
the text DOM monitor. When `ctx.content_ever_changed` is true, the ordinary
stable-text completion paths can break on stable-count/silence or fallback
silence without requiring `not still_generating`. The code only uses
`not still_generating` to tighten thresholds; it does not gate those normal
text exits.

That allows one browser-backed Codex turn to return a stable visible final text
while ChatGPT still exposes an active stop/generating state. The following turn
then correctly hits the pre-fill guard and fails after its bounded wait. This
matches the current live sequence exactly.

The next change should close that lifecycle gap with regression coverage. At a
minimum, ordinary text completion must not report the turn terminal while the
same active-turn generation indicator is still live. Any stale-generation
recovery/interrupt behavior must be separately bounded and proven safe, rather
than solved by simply extending the next-turn pre-fill timeout.


### Runtime fix landed on standalone-dev

The lifecycle fix and focused regression coverage have now been committed to
`standalone-dev`. The current exact head after code, tests, gate documentation,
and a non-semantic line-ending cleanup is:

```text
4adeb956b1f31255a86c56354e3a06eead458b61
```

Final diff from the previous candidate `2b4deda...` is intentionally small:

```text
app/core/stream_monitor.py                 +53 -4
tests/test_stream_monitor_terminal_state.py +56
docs/STANDALONE_S3_LIVE_GATE_2026-09-10.md +63
```

The runtime change requires ordinary text completion to observe
`still_generating=False` before accepting either stable-count or long-silence
termination. Existing image/recovery branches remain separate.

Local validation is now the next step. Do not run full live S3 until the focused
test and repository full pytest suite pass on this exact head.


### 2026-09-19 exact candidate S3 closed

Candidate:

```text
4adeb956b1f31255a86c56354e3a06eead458b61
```

Local validation on the exact candidate:

```text
tests/test_stream_monitor_terminal_state.py
6 passed

related browser/send regressions
31 passed

full suite
501 passed, 22 warnings
```

Candidate-bound live S3 then completed successfully:

```text
S3_PHASE=RESTART_CONTINUITY_PASS
S3_PHASE=COMPACTION_COOLDOWN_PASS
S3_PHASE=COMPACTION_RECOVERY_PASS
S3_REPO_PREFLIGHT=PASS
S3_LISTENER_TRANSITION=RESTARTED
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

This closes the active S3 live blocker on the exact candidate SHA. Do not move
`standalone-dev` before collecting the remaining candidate-bound release
evidence. The next release work is Desktop E2E, clean-checkout install smoke,
CI verification, and S4 release-gate evidence on the same exact SHA.


### Candidate CI status after S3 closure

GitHub Actions for exact candidate
`4adeb956b1f31255a86c56354e3a06eead458b61` now includes a completed
`Standalone CI` pull-request run with conclusion `success`.

The earlier push-triggered run for the same SHA was cancelled because the
pull-request run superseded it; the completed PR run is the usable candidate
CI evidence.

Current exact-candidate matrix:

```text
local focused lifecycle tests   PASS
related browser/send tests      PASS
full local suite                PASS
S3 live                         PASS_LIVE_CLOSED
Standalone CI                   PASS
Desktop E2E                     PENDING
clean-checkout install smoke    PENDING
S4 local release gate           PENDING
```


### Desktop E2E prepare environment mismatch

The first Desktop E2E prepare attempt on exact candidate
`4adeb956b1f31255a86c56354e3a06eead458b61` failed during Python import before
the gate mutated listener, workspace, or Desktop state:

```text
ModuleNotFoundError: No module named 'DrissionPage'
```

The operator invoked the documented `python3 tools/standalone_desktop_e2e_gate.py
prepare` command with the system Python. The repository dependency is declared
in `requirements.txt` as `DrissionPage>=4.0.0,<5.0.0`, while the already
validated project virtual environment contains the runtime dependencies and was
used for S3/local validation.

This is classified as an operator/runtime-environment mismatch rather than a
candidate runtime failure. Keep `standalone-dev` frozen and rerun the Desktop
gate with `.venv/bin/python`. No candidate SHA change is required for this
attempt.


### Desktop E2E operator steps completed, verification pending

On exact candidate `4adeb956b1f31255a86c56354e3a06eead458b61`,
the operator completed the three required real Codex Desktop prompts.

Observed Desktop results:

```text
context step 1: CONTEXT_READY
context step 2: real client exec_command used, final CONTEXT_PASS
multi-file step: files read/modified, unit tests executed, 3 tests passed
```

The first two context prompts were run in the same Desktop thread. The
multi-file prompt was run in a separate Desktop thread, matching the release
gate procedure.

Candidate-bound verification has not yet been recorded. Next action:

```text
.venv/bin/python tools/standalone_desktop_e2e_gate.py verify
```


### Desktop E2E verified on exact candidate

Candidate:

```text
4adeb956b1f31255a86c56354e3a06eead458b61
```

Formal Desktop verification passed:

```text
DESKTOP_CONTEXT=PASS
DESKTOP_LOCAL_TOOLS=PASS
DESKTOP_ROUTE_UWA_CHATGPT_HIGH=PASS
DESKTOP_REQUEST_MANAGER_CLEAN=PASS
DESKTOP_APP_RUNNING=YES
STANDALONE_DESKTOP_E2E=PASS
candidate_commit=4adeb956b1f31255a86c56354e3a06eead458b61
```

Current exact-candidate matrix:

```text
local focused lifecycle tests   PASS
related browser/send tests      PASS
full local suite                PASS
S3 live                         PASS_LIVE_CLOSED
Standalone CI                   PASS
Desktop E2E                     PASS
clean-checkout install smoke    PENDING
S4 local release gate           PENDING
```

Keep `standalone-dev` frozen. Next candidate-bound action is the
clean-checkout install/provider/rollback smoke on the same SHA.


### Install smoke passed; S4 static security doc gap

On exact candidate `4adeb956b1f31255a86c56354e3a06eead458b61`,
clean-checkout install/provider/rollback smoke passed:

```text
INSTALL_SMOKE=PASS
DEPENDENCY_BOOTSTRAP=PASS
ACCEPTANCE_TARGET_RESET=PASS
OFFICIAL_ROLLBACK=PASS
BASIC_CODEX_REQUEST=PASS
AUTH=UNCHANGED
```

The subsequent S4 local gate reached docs/version checks and then failed only on
the SECURITY.md literal requirement:

```text
S4_DOCS_SYNC=PASS
S4_VERSION_SYNC=PASS
STANDALONE_S4_LOCAL=FAIL
FAILURE_CLASS=security
FAILURE_DETAIL=missing=127.0.0.1
```

A full static audit of the remaining S4 document predicates confirmed:
version/tag/changelog, approval markers, stale-text checks, CORS/unsafe markers,
and NOTICE provenance are already satisfied. The only static documentation gap
is the explicit `127.0.0.1` security-default marker.

This requires a documentation commit on `standalone-dev`, which moves the
candidate SHA. Existing S3/Desktop/install results remain valid historical
evidence but must be regenerated on the final frozen SHA before release.


### Final security documentation fix landed

The only remaining static S4 documentation gap was fixed on `standalone-dev`
by explicitly documenting the default loopback bind:

```text
127.0.0.1
```

New exact candidate SHA:

```text
131abfd9cfe6d68ede3e3b34f195ad56ea8aa20f
```

Commit:

```text
131abfd  Document loopback security default
```

No runtime code changed in this candidate transition. Because the release policy
requires exact-SHA evidence, the previous S3, Desktop E2E, and install-smoke
PASS results on `4adeb956...` are historical and must be regenerated on
`131abfd...` before the final S4 candidate-match gate can pass.


### Final candidate static S4 predicates pass

The operator synced `standalone-dev` to:

```text
131abfd9cfe6d68ede3e3b34f195ad56ea8aa20f
```

and ran the static S4 predicates directly. All passed:

```text
S4_DOCS_SYNC=PASS
S4_VERSION_SYNC=PASS
S4_SECURITY_CHECK=PASS
S4_PROVENANCE_CHECK=PASS
```

This confirms the security-document correction closed the only known static S4
gap. Treat `131abfd...` as the frozen final candidate unless a release-blocking
product or release-gate defect is found. Next required evidence is final
candidate-bound S3 Gate B, then Desktop E2E, install smoke, and the complete S4
candidate-match gate on this exact SHA.


### Final candidate S3 Gate B restart-resume mismatch

Frozen candidate:

```text
131abfd9cfe6d68ede3e3b34f195ad56ea8aa20f
```

The final candidate-bound S3 Gate B reached the restart-continuity resume turn
and failed with:

```text
S3_PHASE=RELEASE_PREFLIGHT_PASS
S3_PHASE=ACCEPTANCE_TARGET_RESET
S3_PHASE=BROWSER_SURFACE_PREFLIGHT_PASS
S3_CHATGPT_SURFACE_PREFLIGHT=PASS
S3_PHASE=REPO_PREFLIGHT_PASS
S3_PHASE=UWA_ROUTE_CONFIGURED
S3_PHASE=STANDALONE_LISTENER_READY
S3_PHASE=LOCAL_GATES_PASS
S3_INTER_TURN_COOLDOWN_SEC=58.5
STANDALONE_S3=FAIL
FAILURE_CLASS=restart_resume
FAILURE_DETAIL=final_reply_mismatch
PRIVATE_EVIDENCE_RECORDED=YES
```

A browser screenshot taken after the failure shows a visible
`LARGE_CONTEXT_READY` response with an active Stop button. That marker belongs
to the compaction probe, while this run reported failure before
`RESTART_CONTINUITY_PASS`. Treat the screenshot as suspicious surface state,
not yet as proof of the current failing turn. The next step is to inspect the
private `restart-seed.jsonl`, `restart-resume.jsonl`, acceptance-target reset
metadata, and matching UWA log window. Do not rerun full S3 until the exact final
reply and browser-target ownership are classified.


### Gate B restart-resume root cause fixed

Private trace for candidate
`131abfd9cfe6d68ede3e3b34f195ad56ea8aa20f` confirmed:

```text
seed: CONTEXT_READY
resume exec #1: workspace validation
resume exec #2: write EMBER-7319 to context/result.txt
final: 无法完成所要求的本地 exec_command 读取校验，因此不能据实回复 CONTEXT_PASS。
```

The result file contained the expected token. The missing step was the third
readback `exec_command`.

The post-tool repair policy already recognized two equivalent readback refusal
word orders but missed the live order `cannot -> exec_command -> read/verify`.
That narrow ordering is now covered and regression-tested.

Current `standalone-dev` head after runtime fix, tests, and gate documentation:

```text
8122e87e472ec5becbfa01f2310107d43c8a4d00
```

Candidate transition commits:

```text
bacef19  Repair post-tool readback refusal ordering
6758b0d  Cover Gate B readback refusal wording
8122e87  Record Gate B readback refusal fix
```

Local focused/full validation is pending. Do not rerun full S3 until those tests
pass.


### 8122e87 local regression validation passed

Exact candidate:

```text
8122e87e472ec5becbfa01f2310107d43c8a4d00
```

Local validation after the Gate B readback-refusal repair:

```text
focused post-tool tests: 7 passed
related client-tool policy: 62 passed
full suite: 503 passed, 22 warnings
```

The warnings remain the known FastAPI/Python 3.14
`asyncio.iscoroutinefunction` deprecations.

The focused regression confirms the live refusal wording is now classified and
repaired without breaking the broader client-tool policy suite. The next action
is a full candidate-bound S3 rerun. If restart-resume passes, continue through
compaction and final cleanup on the same SHA.


### Mid-probe rate-limit acknowledgement path gap

On candidate `8122e87e472ec5becbfa01f2310107d43c8a4d00`,
restart continuity passed, then the remote compaction probe failed and the outer
gate classified the visible ChatGPT surface as account-side rate limiting:

```text
S3_PHASE=RESTART_CONTINUITY_PASS
FAILURE_CLASS=remote_compaction_probe
FAILURE_DETAIL=rc=1

outer:
FAILURE_CLASS=chatgpt_web_rate_limited
FAILURE_DETAIL=rate_limited
```

The existing acknowledgement automation is still present. It can physically
click the unique acknowledgement-only button (`Got it` / `明白了` /
`知道了`) in the startup surface preflight, the runtime send guard, and the
post-compaction cooldown path.

The uncovered case is a limiter that appears *during* the request-heavy
compaction probe. The probe returns failure before the post-probe cooldown runs,
and `_external_surface_failure_after_core_failure()` currently performs only a
passive classification recheck. It does not invoke
`dismiss_rate_limit_notice_in_place()`. Therefore the gate fails correctly as
an external limiter but leaves the acknowledgement modal visible.

This does not mean clicking the acknowledgement would make the failed S3 safe to
continue: dismissing the modal only clears the UI notice and does not prove the
account-side limiter has expired. Any fix for this path must clean up the modal
without replaying or automatically continuing the failed probe.


### Mid-probe acknowledgement cleanup fix landed

The previously implemented rate-limit acknowledgement clicker was confirmed
present. The missing path was the outer failure classifier after a compaction
probe failed mid-run.

New `standalone-dev` head:

```text
41018a22c5fb15845c686a0c6e5f462301ce1aee
```

Commits:

```text
d0ad7b3  Dismiss mid-probe rate-limit acknowledgement
743bea5  Cover mid-probe rate-limit cleanup
41018a2  Record mid-probe rate-limit cleanup fix
```

Behavior now:

```text
mid-probe rate limit
-> fail current probe
-> classify chatgpt_web_rate_limited
-> click one acknowledgement-only 明白了/知道了/Got it if uniquely present
-> record sanitized cleanup result
-> do not retry or continue the failed probe
-> preserve rate-limit marker/cooldown for the next S3 run
```

Local focused/full validation is pending.


### Release-critical review after local S3-runner test failure

The first local validation of `41018a2...` exposed two test failures before any
live rerun. Root cause was a real namespace bug in the new mid-probe cleanup
path: `standalone_s3_live_acceptance.py` referenced
`surface_preflight.dismiss_rate_limit_notice_in_place()` even though the
wrapper imports the surface helper through `standalone_s3_live_core as core`.
The same stale namespace was used by the two new test patch targets.

The runtime and tests now consistently use:

```text
core.surface_preflight.dismiss_rate_limit_notice_in_place(...)
```

A broader release-critical static review was also performed before asking for
another local run:

- all `core.<name>` references from the S3 wrapper resolve in
  `standalone_s3_live_core.py`;
- S3 core references to its imported acceptance/helper modules were checked for
  missing attributes;
- Desktop E2E references into S3/core resolve;
- Desktop/install/S4 unit-test patch/reference targets were checked for missing
  exported attributes;
- GitHub CI compiles the S3/Desktop control scripts and runs
  `test_codex_standalone_s3_runner.py` in focused and broad jobs;
- release documentation was audited for the earlier system-Python trap.

That audit found a second concrete issue: the Desktop E2E guide, Desktop
`prepare` completion hint, and S3 live-gate guide still instructed operators
to use system `python3`, even though these release controls import runtime
dependencies such as DrissionPage from the project virtual environment. They
now consistently use `.venv/bin/python`.

Current `standalone-dev` head after these review fixes:

```text
32616917489c41963ee2122133d0e0e56dc29541
```

Relevant follow-up commits:

```text
f6713de  Use core surface preflight for rate-limit cleanup
665063f  Fix rate-limit cleanup test patch targets
5324a0e  Use project Python in Desktop gate hint
3ffc883  Document project Python for Desktop gate
3261691  Document project Python for S3 gate
```

GitHub CI on `3261691...` has already passed scaffold-static,
runtime-import/focused regression, broad Codex regression, and release-metadata;
macOS compatibility was still running at the time of this progress update.

No new full live S3 should be started until the local focused/full regression
passes on this exact SHA and the account-side rate-limit cooldown has cleared.


### 3261691 local release-critical validation passed

Exact candidate:

```text
32616917489c41963ee2122133d0e0e56dc29541
```

Local validation after the namespace/command-documentation review fixes:

```text
S3 runner:        26 passed
release critical: 92 passed
full suite:       504 passed, 22 warnings
```

The warnings remain the known FastAPI/Python 3.14
`asyncio.iscoroutinefunction` deprecations.

The operator did not manually dismiss the old ChatGPT rate-limit acknowledgement
modal. Before the next live S3, use the repository helper to dismiss only the
unique acknowledgement-only rate-limit control in place; this does not send a
message or retry a failed request.


### Repeated rate-limit blocker converted to adaptive acceptance pacing

On exact candidate `32616917489c41963ee2122133d0e0e56dc29541`,
startup acknowledgement cleanup was explicitly verified:

```text
ok=True
dismissed=True
surface_kind=chat
composer_empty=True
blocking_reason=none
```

The subsequent S3 again passed restart continuity and then hit genuine
account-side rate limiting during the remote compaction probe. This confirms the
remaining blocker is request-heavy acceptance pacing rather than the previously
fixed restart/readback or browser lifecycle defects.

The prior recovery logic already increased cross-run cooldown exponentially but
kept the per-turn live gap at a fixed 60 seconds for every rate-limit streak.
That proved insufficient twice.

Current `standalone-dev` head:

```text
673ca4509d6193fe2ce3ff9de17d45dd7c02fbfa
```

New acceptance behavior:

```text
rate-limit streak 1: 60s minimum live-turn gap
rate-limit streak 2+: 120s minimum live-turn gap
terminal cleanup prints S3_RATE_LIMIT_ACK_DISMISSED=YES|NO
```

This changes only release-acceptance pacing and observability. It does not
change product runtime semantics, reduce compaction proof requirements, retry a
failed turn, or bypass account-side limits.

Commits:

```text
26bbfb0  Adapt S3 pacing after repeated rate limits
176cbde  Cover adaptive S3 rate-limit pacing
673ca45  Record adaptive rate-limit pacing
```

Local focused/full validation and CI must pass before the next live S3.


### 673ca45 local validation passed

Exact candidate:

```text
673ca4509d6193fe2ce3ff9de17d45dd7c02fbfa
```

Local validation after adaptive rate-limit pacing:

```text
S3 runner:        27 passed
release critical: 93 passed
full suite:       505 passed, 22 warnings
```

The warnings remain the known FastAPI/Python 3.14
`asyncio.iscoroutinefunction` deprecations.

The next action is one candidate-bound live S3 run. Do not manually clear the
persisted rate-limit marker; the runner should consume it and print the
persisted streak plus the adaptive recovery gap before any request-heavy work.


### 673ca45 live S3: 120-second pacing still hit external limiter

Exact candidate:

```text
673ca4509d6193fe2ce3ff9de17d45dd7c02fbfa
```

The candidate-bound live run proved the new recovery state was active:

```text
S3_RATE_LIMIT_STREAK=2
S3_RATE_LIMIT_RECOVERY_TURN_GAP_SEC=120
S3_INTER_TURN_COOLDOWN_SEC=118.5
S3_PHASE=RESTART_CONTINUITY_PASS
```

The remote compaction probe still encountered a genuine account-side limiter:

```text
FAILURE_CLASS=remote_compaction_probe
FAILURE_DETAIL=rc=1
```

The outer gate correctly promoted it and the new mid-probe cleanup path visibly
closed the acknowledgement modal:

```text
S3_RATE_LIMIT_ACK_DISMISSED=YES
FAILURE_CLASS=chatgpt_web_rate_limited
FAILURE_DETAIL=rate_limited
```

This confirms both the restart/readback fix and the acknowledgement cleanup
work on the exact candidate. Since the per-turn gap is already at the 120-second
design cap, further code churn is not justified by this evidence. The remaining
release blocker is the account's longer rolling request-limit window. Keep the
candidate frozen and retry only after a materially longer quiet period.


### Operator helper import mismatch while reading rate-limit marker

A non-live inline diagnostic attempted to import
`tools.standalone_s3_live_acceptance` from repository root and failed because
that release script intentionally imports sibling modules as top-level modules
when executed from `tools/`:

```text
ModuleNotFoundError: No module named 'standalone_s3_live_core'
```

This is an operator helper-command issue, not a candidate runtime failure. Keep
`standalone-dev` frozen. Read the marker with `PYTHONPATH="$PWD/tools"` and
import `standalone_s3_live_acceptance` as a top-level module, matching normal
script execution semantics.


### Rate-limit quiet window fully expired

For frozen candidate `673ca4509d6193fe2ce3ff9de17d45dd7c02fbfa`,
the persisted rate-limit marker now reports:

```text
RATE_LIMIT_STREAK=3
REMAINING_COOLDOWN_SEC=0.0
```

This is the desired condition before the next live attempt: the cross-run quiet
window has fully expired, while the persisted streak will still force the
maximum configured recovery pacing of 120 seconds between live turns.

Next action: run exactly one full candidate-bound S3 attempt. Do not manually
clear the marker and do not immediately retry again if the account-side limiter
returns.


### 673ca45 next live attempt: remote compaction failed, outer classification pending

Exact candidate remains:

```text
673ca4509d6193fe2ce3ff9de17d45dd7c02fbfa
```

The next candidate-bound run started with the persisted recovery state and
maximum pacing:

```text
S3_RATE_LIMIT_STREAK=3
S3_RATE_LIMIT_RECOVERY_TURN_GAP_SEC=120
S3_INTER_TURN_COOLDOWN_SEC=118.4
S3_PHASE=RESTART_CONTINUITY_PASS
```

The inner compaction probe then returned:

```text
FAILURE_CLASS=remote_compaction_probe
FAILURE_DETAIL=rc=1
```

At the time of this progress update, the operator had not yet provided the
outer post-failure surface classification. Do not classify this specific run as
account-side rate limiting until either the outer wrapper reports
`chatgpt_web_rate_limited` or the private probe/browser evidence shows it.
No candidate code change is justified yet.


### 673ca45 live S3: failure is not currently classified as rate limiting

The operator inspected the exact outer result for the latest run. It remained:

```text
STANDALONE_S3=FAIL
FAILURE_CLASS=remote_compaction_probe
DETAIL=rc=1
candidate_commit=673ca4509d6193fe2ce3ff9de17d45dd7c02fbfa
```

The probe summary shows the seed succeeded and the very first coarse filler turn
failed despite the maximum 120-second recovery pacing:

```text
CONTEXT_WINDOW=77000
TRIGGER_TARGET_LIMIT=73150
COARSE_BYTES=46000
COARSE_PROMPT_CHARS=15767
SEED_REPLY_EXACT=YES
S3_INTER_TURN_COOLDOWN_SEC=120.0
RUN_FAIL coarse_turn_failed round=1 rc=1
```

There was no `rate-limit-failure-cleanup.json`, and the outer wrapper did not
promote the result to `chatgpt_web_rate_limited`. Therefore this specific run
must not be treated as an account-side rate-limit failure yet.

The previously shown restart trace is not the failing compaction trace. The next
diagnostic must locate the probe's emitted `PRIVATE_TRACE_DIR` and inspect only
the exact `trigger-probe-01-coarse.jsonl` plus matching UWA error/status lines.
No candidate code change and no new live retry until that failure is classified.


### Root cause found: localized Stop control invisible to stream completion detector

The exact failed coarse trace for the latest `673ca45...` S3 run is:

```text
stream disconnected before completion:
send_blocked_by_preexisting_generation
```

The browser timeline shows the preceding seed was reported as stream-complete,
then the next request still observed the old generation/Stop state after 120
seconds of pacing and waited the full 300-second pre-fill idle timeout.

Root cause: lifecycle detector drift. `GeneratingStatusCache` did not include
the localized Chinese Stop selector that the pre-send guard already recognized.
On a Chinese ChatGPT surface, the stream monitor could therefore set
`still_generating=False` prematurely even though the next-send guard correctly
saw the generation as active.

The fix makes stream completion and pre-send idle protection consume one shared
selector set from `app/core/generation_state.py`, including Chinese Stop and
ChatGPT stop-button selectors. Focused regression coverage reproduces the
localized generation state and verifies the pre-send probe uses the same shared
selectors. CI now explicitly runs this terminal-state regression.

Current `standalone-dev` head:

```text
d4eadc2ee4a6c07dfa90890f6350d69e739659b6
```

Commits:

```text
894afae  Share browser generation indicators
904a419  Align stream generation detection with shared selectors
7cc6e8d  Share generation indicators with pre-send guard
f161aef  Cover localized active-generation detection
5c62fe9  Verify pre-send guard shares generation selectors
38fd160  Run generation lifecycle regression in CI
d4eadc2  Record localized generation lifecycle fix
```

The broad UWA log also contained an HTTP 413 event, but it is not the failing
coarse-turn trace. No further S3 run until local focused/full tests and exact-SHA
CI pass.


### Localized-generation regression assertion corrected

The first local run on `d4eadc2...` failed only in the new
`test_pre_send_probe_uses_same_localized_generation_selectors` assertion.
Runtime code had serialized the shared selector list into JavaScript via
`json.dumps(..., ensure_ascii=False)`, so selector-internal double quotes are
correctly escaped inside the emitted JSON string literal. The test incorrectly
searched for the unescaped raw CSS substring.

The test now asserts the exact serialized shared selector array injected into
the pre-send probe JavaScript. Runtime implementation is unchanged.

Current `standalone-dev` head:

```text
df0ffa0384bb3ba976299cde85169a7c6aabc6ed
```

Commit:

```text
df0ffa0  Assert serialized shared generation selectors
```

Re-run the localized lifecycle regression and full suite before any live S3.


### df0ffa0 local lifecycle validation passed

Exact candidate:

```text
df0ffa0384bb3ba976299cde85169a7c6aabc6ed
```

Local validation after the localized generation-state fix and corrected serialized-selector assertion:

```text
generation lifecycle: 10 passed
related runtime:       63 passed, 22 warnings
full suite:            509 passed, 22 warnings
```

The warnings remain the known FastAPI/Python 3.14
`asyncio.iscoroutinefunction` deprecations.

Next gate: exact-SHA CI must finish successfully before another live S3 run.


### df0ffa0 live S3 reached post-compaction recovery

Exact candidate:

```text
df0ffa0384bb3ba976299cde85169a7c6aabc6ed
```

Local validation and exact-SHA CI were green before this live run:

```text
generation lifecycle: 10 passed
related runtime:       63 passed, 22 warnings
full suite:            509 passed, 22 warnings
Standalone CI:         PASS
```

The live run materially advanced past the previously failing first coarse turn.
It reached:

```text
S3_PHASE=RESTART_CONTINUITY_PASS
S3_COMPACTION_COOLDOWN_SEC=180
S3_PHASE=COMPACTION_COOLDOWN_PASS
```

and then failed only in the final same-thread post-compaction recovery:

```text
STANDALONE_S3=FAIL
FAILURE_CLASS=post_compaction_recovery
FAILURE_DETAIL=final_reply_mismatch
PRIVATE_EVIDENCE_RECORDED=YES
```

This is strong live evidence that the shared localized generation-state selector
fix closed the prior `send_blocked_by_preexisting_generation` blocker. Do not
change candidate code until the exact `post-compaction-recovery.jsonl` is
classified: inspect final agent text, client commands/results, and whether
`large_context/result.txt` exists with the expected token.


### df0ffa0 post-compaction provenance gap fixed

The post-compaction recovery trace showed that multiple real client workspace
commands completed successfully, but the final model reply incorrectly claimed
that the declared workspace tool was unavailable. The existing refusal-language
matcher already covered the wording.

The actual gap was provenance after recursive compaction. A Responses
continuation can retain a completed client tool result as the bridge-generated
`[Function Call Output ...]` user fallback after the matching structured
assistant function call has been compacted out. The main repair path previously
required structured tool history and therefore missed this case.

The policy now accepts that generated fallback as prior workspace-tool
provenance only when the same request also contains a compacted unresolved
workspace continuation. A fallback-shaped user message without compacted
workspace state remains insufficient.

Current `standalone-dev` head:

```text
255791ba9c734c20b9aad7250ba8a624264698db
```

Commits:

```text
fbd47d5  Repair compacted function-output tool refusals
9073f9c  Cover compacted function-output refusal recovery
255791b  Record compacted function-output refusal fix
```

Do not run live S3 until focused/full local validation and exact-SHA CI are
green.


### 255791b local post-compaction validation passed

Exact candidate:

```text
255791ba9c734c20b9aad7250ba8a624264698db
```

Local validation after the compacted function-output provenance repair:

```text
exact post-compaction regression: 13 passed
client tool policy family:        116 passed, 8 warnings
full suite:                       512 passed, 22 warnings
```

The warnings remain the known FastAPI/Python 3.14
`asyncio.iscoroutinefunction` deprecations.

Next gate: exact-SHA CI must be green before the next candidate-bound live S3
attempt.


### 255791b live S3 cooldown completed normally

During the next candidate-bound S3 run on
`255791ba9c734c20b9aad7250ba8a624264698db`, the operator initially reported a
long quiet interval after:

```text
S3_COMPACTION_COOLDOWN_SEC=180
```

Read-only diagnostics showed the S3 process still alive, UWA healthy,
`running_count=0`, no active ChatGPT rate limit, and the remote compaction flow
had completed successfully. The UWA log showed the last compaction/probe request
completed at approximately 14:59:14.

The terminal then advanced at 15:02:16 with:

```text
S3_PHASE=COMPACTION_COOLDOWN_PASS
```

This matches the configured 180-second quiet period plus surface recheck and is
not a hang. After this point the runner enters the single post-compaction
recovery turn, whose configured timeout is 900 seconds. No intervention or
candidate change is justified while that recovery turn is still within its
timeout window.


### 255791b live S3: post-compaction tool refusal persists in affinity delta

Exact candidate:

```text
255791ba9c734c20b9aad7250ba8a624264698db
```

The live run again passed restart continuity, the full remote compaction probe,
and the configured 180-second cooldown, then failed at the single
post-compaction recovery turn:

```text
S3_PHASE=RESTART_CONTINUITY_PASS
S3_PHASE=COMPACTION_COOLDOWN_PASS
STANDALONE_S3=FAIL
FAILURE_CLASS=post_compaction_recovery
FAILURE_DETAIL=final_reply_mismatch
```

The visible final Web reply retained the durable token `ORBIT-5921` and the
pending write/readback task, but still claimed that the current ChatGPT session
had no real callable local `exec_command` interface and refused to return
`LARGE_CONTEXT_PASS`.

Source inspection shows the refusal wording is already matched by the existing
post-tool unavailable patterns. The remaining gap is provenance in a reused
ChatGPT affinity delta: a raw Responses `function_call_output` can be normalized
to the bridge-generated user-shaped `[Function Call Output ...]` fallback after
its matching assistant function call has been compacted out. The repair policy
cannot reliably distinguish that generated fallback from arbitrary user text
because normalization currently preserves provenance only in the text marker.

Next fix: carry an internal non-prompt metadata marker on generated
function-output fallback messages, and let the post-tool repair policy treat
that marker as authoritative workspace-tool provenance. The marker must remain
internal and must not be serialized into browser-visible prompt content.


### Affinity-delta provenance marker fix landed

The repeated post-compaction failure on `255791ba...` was traced to an
affinity-delta provenance gap. The model retained the durable token and pending
workspace action but again claimed that the current ChatGPT session had no real
callable local workspace tool. The refusal wording itself was already covered.

A generated Responses `function_call_output` fallback now carries internal
metadata proving that it came from a real tool result. The client-tool policy
accepts that marker as prior workspace-tool provenance even when the current
browser delta omits the compacted summary because that summary already exists in
the open ChatGPT conversation. Browser prompt serialization ignores the private
marker, and an unmarked user-authored fallback-looking string does not gain the
same authority.

Current `standalone-dev` head:

```text
23652871f9fc4f901ee68ee7ab9db18ee13a4177
```

Implementation commits:

```text
f34ad2f  Mark generated Responses tool-output fallbacks
311a7f9  Trust internal Responses tool-output provenance
7e11350  Cover internal tool-output fallback provenance
63f0223  Cover affinity-delta tool-output provenance repair
3511f5e  Verify provenance marker stays browser-internal
2365287  Record affinity-delta provenance marker fix
```

Do not run live S3 until focused/full local validation and exact-SHA CI are
green.


### 2365287 local affinity-provenance validation passed

Exact candidate:

```text
23652871f9fc4f901ee68ee7ab9db18ee13a4177
```

Local validation after the internal Responses tool-output provenance marker fix:

```text
exact affinity provenance regression: 27 passed, 8 warnings
related client tool policy:            119 passed, 8 warnings
full suite:                            516 passed, 22 warnings
```

The warnings remain the known FastAPI/Python 3.14
`asyncio.iscoroutinefunction` deprecations.

Next gate: exact-SHA CI must be green before the next candidate-bound live S3
attempt.


### 2365287 live S3 exposed an affinity missing-task clarification loop

Exact candidate:

```text
23652871f9fc4f901ee68ee7ab9db18ee13a4177
```

The live run again passed restart continuity, remote compaction, and the
180-second cooldown, then failed post-compaction recovery with
`final_reply_mismatch`.

The visible Web reply showed that the prior provenance fix changed behavior as
intended: the model now acknowledged that `exec_command` and `write_stdin`
were available. It then incorrectly asked the user to provide the concrete
workspace task again instead of continuing the retained large-context recovery.

Two gaps were fixed:

1. The missing-task clarification matcher now covers the observed
   `请直接给出 ... 具体任务` wording.
2. When a generated tool-result fallback is sent as an affinity delta after
   recursive compaction, the newest compacted continuation text from the fully
   hydrated state is carried as private internal metadata. The client-tool
   policy uses it for compacted-workspace detection and focused repair prompts.
   The private state is not serialized into browser-visible prompt content.

Current `standalone-dev` head:

```text
83443230f853e1f6aaf88dadc174831fba7acfec
```

Implementation commits:

```text
8afa1a2  Carry compacted state in affinity tool-result metadata
ec00e1b  Repair affinity missing-task continuation
86ce841  Cover compacted context on affinity tool-result delta
e107449  Cover live affinity missing-task recovery
8344323  Record affinity missing-task continuation fix
```

Do not run live S3 until focused/full local validation and exact-SHA CI are
green.
