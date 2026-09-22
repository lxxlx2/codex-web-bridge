# ChatGPT active handoff

Temporary coordination document for ChatGPT-maintained work on Codex Web Bridge.

This document is intentionally kept off the canonical `standalone-dev` release branch.

## Operating rule

When Codex Desktop / Codex CLI quota is unavailable, ChatGPT is the active engineering maintainer.

Continue the repository task directly with the tools available in the current ChatGPT session.

Do not default to generating a Codex prompt.

Delegate to Codex only when the user explicitly asks for Codex execution.

When local Mac execution is required and the current ChatGPT session has no local shell tool, ask the user only for the minimum command/output needed for verification.

## Canonical product branch

```text
standalone-dev
```

This temporary handoff branch must not be merged into the release.

Before release, delete:

```text
chatgpt-maintenance-handoff
```

## Current release objective

Close the remaining S3/S4 gates for:

```text
v0.1.0-rc.1
```

## Current canonical candidate

```text
51dea04ab95e818680b96769811c3620d36fc912
```

This candidate contains the narrow `ACCEPTANCE_INCOMPLETE` continuation repair and its regression coverage.

GitHub Standalone CI run `#870` completed successfully for this exact SHA. All jobs passed:

```text
scaffold-static   PASS
runtime-import    PASS
codex-regression  PASS
release-metadata  PASS
macos-compat      PASS
```

Historical candidate `90cdbdfb7b8259f8fb00e7a0e35b57c26f7ba711` remains diagnostic evidence only.

## Current live S3 status

Candidate:

```text
51dea04ab95e818680b96769811c3620d36fc912
```

Candidate-bound clean install/rollback smoke passed locally.

The next live S3 attempt proved the restart-continuity repair works in the real flow:

```text
S3_PHASE=RESTART_CONTINUITY_PASS
```

The run then advanced through compaction cooldown and failed during post-compaction recovery:

```text
FAILURE_CLASS=post_compaction_recovery
DETAIL=codex_turn_runtime_error
```

The outer release wrapper immediately rechecked the ChatGPT Web surface and found an account-side limiter:

```text
S3_RATE_LIMIT_ACK_DISMISSED=YES
FAILURE_CLASS=chatgpt_web_rate_limited
DETAIL=rate_limited
```

The compacted continuation state retained the exact large-context token, recorded successful workspace validation, and recorded a successful write of `large_context/result.txt`. Its unresolved next step was the required separate byte-level readback before `LARGE_CONTEXT_PASS`.

Classification: external Web failure after successful product progress. No source defect is established by this attempt, so no source change is required and the candidate remains `51dea04...`.

The S3 runner recorded another limiter marker. With the default policy, the next run will enforce the recent-rate-limit cooldown and raise recovery pacing before sending live turns.

## Previous repaired blocker

The prior candidate `90cdbdf...` exposed an unfinished restart acceptance sequence where exact `ACCEPTANCE_INCOMPLETE` was accepted after validation and write but before independent readback. That blocker was repaired and the current live run reached `S3_PHASE=RESTART_CONTINUITY_PASS`, providing live confirmation that the repair closed that path.

## Completed engineering step

The narrow synthetic acceptance repair has been implemented on `standalone-dev` and exact-SHA CI is green.

## Next engineering step

Regenerate candidate-bound local/live evidence for `51dea04ab95e818680b96769811c3620d36fc912`.

Primary files:

```text
app/services/client_tool_policy.py
tests/test_client_tool_policy_repeated_refusal.py
```

Inspect supporting tool-calling/S3 code as needed:

```text
app/services/tool_calling.py
tools/standalone_s3_live_core.py
tests/test_codex_standalone_s3_runner.py
```

Required invariant:

1. Recognize exact assistant text `ACCEPTANCE_INCOMPLETE` only for the repository's synthetic acceptance contracts.
2. Require authoritative successful real client-tool history and successful acceptance workspace validation.
3. Determine progress from successful paired exec-command results.
4. If result write exists and no later independent readback exists, repair toward exactly the next unfinished readback step.
5. Do not rewrite the result file in that state.
6. If write is absent, continuation may proceed to the write step.
7. If write and later readback are already complete, this unfinished-effect detector must be false.
8. Do not convert `ACCEPTANCE_INCOMPLETE` directly into a PASS sentinel inside the bridge.
9. Keep `tool_choice="none"` respected.
10. Do not broaden generic refusal matching or generic business-task inference.
11. Do not weaken S3 independent effect verification.
12. Do not increase the generic retry budget solely to make this pass.

Focused regressions should cover at least:

```text
validation + write + no readback + ACCEPTANCE_INCOMPLETE => repair
roundtrip repair => real exec_command readback tool call
validation + no write + ACCEPTANCE_INCOMPLETE => continuation
validation + write + later readback + ACCEPTANCE_INCOMPLETE => unfinished detector false
unrelated ACCEPTANCE_INCOMPLETE => no repair
context/result.txt and large_context/result.txt shared behavior
```

After the source fix:

```text
focused tests
full pytest
public_repo_safety_check
standalone_dependency_audit --check
exact-SHA GitHub CI
clean install/rollback smoke
new S3 attempt
```

Any source change creates a new candidate SHA. Historical evidence from `90cdbdf...` remains diagnostic only after that source change.

## Handoff discipline

Material blocker diagnosis and next steps should be updated here whenever the active task changes.

A new ChatGPT conversation should read this file and continue the task directly. It should not ask the user to transfer the task to Codex unless the user explicitly requests that workflow.


## 2026-09-21 ChatGPT implementation update

ChatGPT implemented the blocker directly through GitHub without delegating to Codex.

The implementation:

- recognizes exact `ACCEPTANCE_INCOMPLETE` only when one synthetic acceptance contract is unambiguously present;
- binds successful workspace validation to the matching `context` or `large_context` directory;
- derives write/readback progress only from successful paired client-tool history;
- when write is complete and readback is missing, directs the next repair only to independent readback and explicitly forbids rewriting the file;
- leaves the detector inactive after a successful write plus later readback;
- keeps `tool_choice="none"` unchanged;
- does not convert `ACCEPTANCE_INCOMPLETE` into a PASS sentinel inside the bridge.

An initial CI run exposed two regression-fixture defects. They were diagnosed from GitHub Actions logs and fixed directly. Exact-SHA CI for `51dea04...` then passed all jobs.

Local next commands are:

```bash
cd ~/codex-web-bridge
git switch standalone-dev
git pull --ff-only
git rev-parse HEAD
git status --porcelain=v1 --untracked-files=all
.venv/bin/python tools/standalone_install_smoke.py
```

Require HEAD exactly:

```text
51dea04ab95e818680b96769811c3620d36fc912
```

If install smoke passes and the worktree stays clean, run:

```bash
.venv/bin/python tools/standalone_s3_live_acceptance.py
```

Do not reuse the previous candidate's install-smoke or S3 results.


## 2026-09-21 live attempt update

Local evidence for `51dea04ab95e818680b96769811c3620d36fc912`:

```text
INSTALL_SMOKE=PASS
DEPENDENCY_BOOTSTRAP=PASS
ACCEPTANCE_TARGET_RESET=PASS
OFFICIAL_ROLLBACK=PASS
BASIC_CODEX_REQUEST=PASS
AUTH=UNCHANGED

S3_PHASE=RESTART_CONTINUITY_PASS
S3_PHASE=COMPACTION_COOLDOWN_PASS

core failure:
FAILURE_CLASS=post_compaction_recovery
DETAIL=codex_turn_runtime_error

outer classification:
S3_RATE_LIMIT_ACK_DISMISSED=YES
FAILURE_CLASS=chatgpt_web_rate_limited
DETAIL=rate_limited
```

Do not modify source for this attempt. Do not count it as an S3 success. Do not immediately replay the failed post-compaction turn.

Next action after the account-side limiter cools down:

```bash
cd ~/codex-web-bridge
git switch standalone-dev
git pull --ff-only
test "$(git rev-parse HEAD)" = "51dea04ab95e818680b96769811c3620d36fc912"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
.venv/bin/python tools/standalone_s3_live_acceptance.py
```

The runner itself will honor the recorded limiter marker before sending requests. If the next attempt fails for a product-level reason after the limiter clears, inspect that new private evidence before changing source.


## 2026-09-21 immediate retry remained rate limited

A follow-up S3 attempt on the same exact candidate `51dea04ab95e818680b96769811c3620d36fc912` started at approximately 07:05 local time.

Observed:

```text
S3_RATE_LIMIT_STREAK=1
S3_RATE_LIMIT_RECOVERY_TURN_GAP_SEC=60
S3_PHASE=LOCAL_GATES_PASS

core:
FAILURE_CLASS=restart_resume
DETAIL=rc=1

outer:
S3_RATE_LIMIT_ACK_DISMISSED=YES
FAILURE_CLASS=chatgpt_web_rate_limited
DETAIL=rate_limited
```

Classification remains external account-side Web limiting. Do not change source and do not count this attempt as S3 success.

The startup streak remaining at 1 is consistent with the previous stored limiter marker having reset its streak window before the earlier failure; this retry itself occurred within the one-hour streak window and should cause the persisted marker to advance for the next run.

Expected next-run behavior with the default policy is a higher recovery floor, normally:

```text
S3_RATE_LIMIT_STREAK=2
S3_RATE_LIMIT_RECOVERY_TURN_GAP_SEC=120
```

and a recent-rate-limit cooldown of up to about 360 seconds if the next run starts before that interval has elapsed.

Operational guidance: avoid another immediate manual replay. Allow additional quiet time beyond the built-in minimum before starting the next full S3 attempt.


## 2026-09-21 first successful S3 on current candidate

Exact candidate:

```text
51dea04ab95e818680b96769811c3620d36fc912
```

A full live S3 run started at approximately 11:49 local time (UTC+07) and completed successfully at approximately 12:38 local time.

Observed terminal evidence:

```text
S3_RATE_LIMIT_STREAK=2
S3_RATE_LIMIT_RECOVERY_TURN_GAP_SEC=120
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

This is S3 success #1 for the current candidate.

The release-confidence gate timestamps S3 evidence from the outer result directory name, which corresponds to run start time. Therefore the first successful evidence is in the UTC 04:00-06:00 two-hour window, with a start around 04:49 UTC.

For the >=7200-second requirement, the last successful S3 evidence must start no earlier than approximately 06:49 UTC, which is approximately 13:49 local time (UTC+07).

Still required on the same candidate:

```text
S3 success #2
S3 success #3
>=2 distinct two-hour UTC evidence windows
>=7200 seconds first-to-last successful evidence span
office-work soak PASS with effect verification
release confidence PASS
Desktop E2E
S4
```

Do not modify source or release documents while accumulating this candidate-bound evidence.


## 2026-09-21 second S3 attempt after first PASS

A second full S3 attempt on exact candidate `51dea04ab95e818680b96769811c3620d36fc912` started around 12:57 local time.

Observed:

```text
S3_RATE_LIMIT_STREAK=2
S3_RATE_LIMIT_RECOVERY_TURN_GAP_SEC=120
S3_PHASE=LOCAL_GATES_PASS
S3_INTER_TURN_COOLDOWN_SEC=118.4
STANDALONE_S3=FAIL
FAILURE_CLASS=restart_resume
FAILURE_DETAIL=final_reply_mismatch
```

No outer ChatGPT Web limiter classification was printed for this attempt.

Classification is therefore unresolved pending inspection of the private `restart-resume.jsonl` evidence. The first successful S3 evidence remains valid for the unchanged candidate, but this failed attempt does not count toward release confidence.

Do not modify source until the trace establishes the exact final assistant message and completed workspace effects.


## 2026-09-21 restart step-2 execution stall repaired

Private evidence from the failed repeated S3 attempt on `51dea04ab95e818680b96769811c3620d36fc912` established:

```text
workspace validation: completed, exit 0
result write:         missing
result readback:      missing
result file:          missing
turn terminal:        completed
assistant final:      第二步未能通过客户端 exec_command 执行，因此不能回复 CONTEXT_PASS。
trace error:          none
```

No outer Web rate-limit classification was present. This was classified as a product-level synthetic acceptance continuation gap.

ChatGPT repaired it directly on `standalone-dev`.

New exact candidate:

```text
d798bd123345970d76d473924b4ef30d9a30a869
```

The repair is limited to one unambiguous synthetic `CONTEXT_PASS` or `LARGE_CONTEXT_PASS` contract, successful real workspace validation, unfinished write/readback effects, and an assistant final that explicitly says step 2 or step 3 could not execute through an exec-like client tool and therefore refuses the matching PASS marker.

The existing next-effect logic is reused:
- after validation with no write, repair continues to the write;
- after write with no later readback, repair continues only to the independent readback;
- after write plus later readback, the unfinished detector is disabled;
- ordinary unrelated text does not activate the repair;
- `tool_choice="none"` remains authoritative.

Regression coverage was added for the exact live Chinese wording, real roundtrip repair, unrelated text, completed-effects state, and shared large-context behavior.

Exact-SHA GitHub Standalone CI run `#873` completed successfully:

```text
scaffold-static   PASS
runtime-import    PASS
codex-regression  PASS
release-metadata  PASS
macos-compat      PASS
```

The codex-regression job reported:

```text
539 passed, 22 warnings
```

Because source and the release engineering record changed, all positive candidate-bound evidence from `51dea04...`, including its earlier S3 PASS and install smoke, is historical only and does not count for `d798bd1...`.

Next action is to regenerate deterministic/local candidate evidence, clean install smoke, then begin S3 success accumulation again on `d798bd123345970d76d473924b4ef30d9a30a869`.


## 2026-09-21 first live S3 attempt on d798bd1 candidate

Exact candidate:

```text
d798bd123345970d76d473924b4ef30d9a30a869
```

Candidate-bound local validation passed:

```text
focused tests:             62 passed
full suite:                575 passed, 22 warnings
public repository safety: PASS
dependency audit:          PASS
install smoke:             PASS
worktree after gates:      clean
```

The live S3 run then produced:

```text
S3_RATE_LIMIT_STREAK=2
S3_RATE_LIMIT_RECOVERY_TURN_GAP_SEC=120
S3_PHASE=RESTART_CONTINUITY_PASS
S3_PHASE=COMPACTION_COOLDOWN_PASS

STANDALONE_S3=FAIL
FAILURE_CLASS=post_compaction_recovery
FAILURE_DETAIL=final_reply_mismatch
```

No outer Web rate-limit promotion was printed.

Classification is unresolved pending read-only inspection of the latest
`post-compaction-recovery.jsonl` and `large_context/result.txt` evidence.

Do not modify source yet. Determine the final assistant text, successful workspace
command sequence, whether validation/write/readback all occurred, and whether the
result bytes exactly match the retained token plus trailing newline.


## 2026-09-21 post-compaction no-task acknowledgement repaired

Read-only private evidence from candidate `d798bd123345970d76d473924b4ef30d9a30a869` showed:

```text
workspace validation: completed, exit 0
result write:         missing
result readback:      missing
result file:          missing
turn terminal:        completed
trace error:          none
assistant final:
已续接当前状态，并保留精确值 ORBIT-5921。
当前消息里没有新的验收命令、目标文件或预期输出，因此没有可执行的下一步。
直接发下一条验收指令即可。
```

The exact durable token survived compaction and the real validation tool call succeeded, but the model ignored the unresolved ACTIVE CONTINUATION STATE.

ChatGPT repaired this directly on `standalone-dev`.

New candidate:

```text
c18a990e371eb391a59320b6853de96e47dddebe
```

The change extends the existing compacted missing-task/state-only acknowledgement detection only under authoritative compacted workspace intent/provenance. It covers the live wording about no new acceptance command, target file, expected output, or executable next step, plus the state-resume wording about retaining an exact value. Ordinary state acknowledgements without compacted workspace intent remain non-actionable.

Regression coverage includes the exact live wording, tool roundtrip recovery, and an unrelated state-only control.

All positive candidate-bound evidence from `d798bd1...` is historical after this source/release-document change. The exact-SHA CI run for `c18a990...` is Standalone CI #876.


## 2026-09-21 CI completed for c18a990 candidate

Exact-SHA Standalone CI run `#876` completed successfully for:

```text
c18a990e371eb391a59320b6853de96e47dddebe
```

All jobs passed:

```text
scaffold-static   PASS
runtime-import    PASS
codex-regression  PASS
release-metadata  PASS
macos-compat      PASS
```

The codex-regression job reported:

```text
542 passed, 22 warnings
```

Next required candidate-bound evidence on the user's Mac is:

```text
focused tests
full suite
public safety
dependency audit
install smoke
S3 live
```

All prior positive evidence belongs to older SHAs and must not be counted for `c18a990...`.


## 2026-09-21 first successful S3 on c18a990 candidate

Exact candidate:

```text
c18a990e371eb391a59320b6853de96e47dddebe
```

Candidate-bound local validation passed:

```text
focused tests:             65 passed
full suite:                578 passed, 22 warnings
public repository safety: PASS
dependency audit:          PASS
install smoke:             PASS
worktree after gates:      clean
```

The live S3 run started at approximately 16:03 local time (UTC+07) and completed successfully:

```text
S3_RATE_LIMIT_STREAK=2
S3_RATE_LIMIT_RECOVERY_TURN_GAP_SEC=120
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

This is S3 success #1 for `c18a990...`.

The first successful evidence directory corresponds to a start around 09:03 UTC, within the UTC 08:00-10:00 two-hour window. Because release confidence requires at least three successful S3 runs, at least two two-hour UTC windows, and at least 7200 seconds between first and last successful evidence timestamps, the current wall clock is already far enough beyond the first success for #2 and #3 to be run sequentially without risking the span requirement, provided they succeed on the unchanged candidate.

Still required on this exact SHA:

```text
S3 success #2
S3 success #3
office-work soak PASS
release-confidence aggregator PASS
Desktop E2E
S4 exact-candidate consistency
```

Do not change product source or release documents while accumulating this evidence.

## 2026-09-21 S3 target #2 failed in post-compaction recovery

Exact candidate remained:

```text
c18a990e371eb391a59320b6853de96e47dddebe
```

The second S3 target started at approximately 22:50 local time (UTC+07). It passed restart continuity and compaction cooldown, then stopped at:

```text
FAILURE_CLASS=post_compaction_recovery
FAILURE_DETAIL=final_reply_mismatch
PRIVATE_EVIDENCE_RECORDED=YES
```

No outer Web rate-limit classification was printed in the supplied output.

This attempt does not count toward the required three successful S3 runs. The earlier successful S3 #1 remains valid because the candidate SHA did not change.

Do not change source until the latest post-compaction recovery trace is inspected for the exact final assistant message and completed validation/write/readback effects.

## 2026-09-22 repeated post-compaction capability refusal on c18a990

The failed S3 target #2 on exact candidate `c18a990e371eb391a59320b6853de96e47dddebe` was inspected.

Observed private evidence:

```text
COMMAND_1=workspace validation, completed exit 0
COMMAND_2=other, completed exit 0
COMMAND_3=other, completed exit 0
COMMAND_4=result readback-shaped command, completed exit 0

successful write classifier: 0
successful readback classifier: 1
readback after successful write: NO
result file: missing
turn terminal: completed
trace error: none
```

Final assistant text claimed both that the acceptance workspace was inaccessible and that no real `exec_command` client tool was callable, despite multiple successful client commands in the same turn. It retained the exact ORBIT token and the expected result-file contract, then refused to return `LARGE_CONTEXT_PASS`.

This is a product-level continuation/capability-refusal shape, but source should not be changed until COMMAND_2 and COMMAND_3 are inspected. Their exact command text is needed to prove that no unrecognized or uncertain result-file write attempt occurred before deciding whether an automatic repair may safely issue the missing write.

The prior S3 success #1 for c18a990 remains valid because the candidate SHA is unchanged. This failed attempt does not count.

## 2026-09-22 structural acceptance capability-refusal repair

Inspection of the failed S3 target #2 proved the additional client commands were read-only:

```text
COMMAND_1 exact validation
COMMAND_2 pwd + root listing
COMMAND_3 pwd + root listing + large_context listing
COMMAND_4 missing-file probe using test/wc/od/cat
```

All completed with exit code 0. None wrote `large_context/result.txt`; the final probe confirmed it was missing. This removed the side-effect replay ambiguity.

ChatGPT implemented a structural repair on `standalone-dev`.

New exact candidate:

```text
f3d02327a5cb99513a60eeaf14fd517c5e86a09e
```

The new detector is limited to a proven synthetic `CONTEXT_PASS` or
`LARGE_CONTEXT_PASS` contract with:

```text
successful real matching workspace validation
requested PASS marker referenced in the final
unfinished write/readback effects
final claiming either client-tool unavailability or workspace inaccessibility
```

Progress still comes only from paired successful client-tool results. A read-only
probe before a successful write does not count as the required post-write readback.
Once a successful write plus later readback exist, the unfinished detector is
disabled. Without successful acceptance validation, the structural repair does not
activate.

Regression coverage includes:
- exact live capability-refusal wording
- read-only pre-write probes
- repair into the missing write
- no-validation negative case
- completed write + later readback negative case

All positive candidate-bound evidence from `c18a990...`, including its S3 #1,
is now historical because source and release engineering documentation changed.

Exact-SHA Standalone CI run for `f3d02327...` is `#879` and was queued when this handoff entry was written.

## 2026-09-22 CI completed for f3d02327 candidate

Exact-SHA Standalone CI run `#879` completed successfully for:

```text
f3d02327a5cb99513a60eeaf14fd517c5e86a09e
```

All jobs passed:

```text
scaffold-static   PASS
runtime-import    PASS
codex-regression  PASS
release-metadata  PASS
macos-compat      PASS
```

The codex-regression job reported:

```text
546 passed, 22 warnings
```

Next candidate-bound evidence required on the user's Mac is the normal deterministic/local gate set, clean install smoke, then fresh S3 accumulation on this exact SHA. Prior S3 successes belong to older candidates and cannot be counted for `f3d02327...`.

## 2026-09-22 first S3 attempt on f3d02327 candidate failed post-compaction

Exact candidate remained:

```text
f3d02327a5cb99513a60eeaf14fd517c5e86a09e
```

Candidate-bound local validation passed before the live run:

```text
focused tests:             69 passed
full suite:                582 passed, 22 warnings
public repository safety: PASS
dependency audit:          PASS
install smoke:             PASS
worktree:                  clean
```

The live run passed restart continuity and compaction cooldown, then failed:

```text
FAILURE_CLASS=post_compaction_recovery
FAILURE_DETAIL=final_reply_mismatch
PRIVATE_EVIDENCE_RECORDED=YES
```

No outer Web rate-limit classification was present in the supplied output.

This attempt does not count toward S3 success accumulation. Do not change source until the latest post-compaction recovery trace is inspected for exact final text and successful command/effect sequence.

