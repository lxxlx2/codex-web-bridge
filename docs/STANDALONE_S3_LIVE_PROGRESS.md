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
