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

## 2026-09-22 Astra interrupted review surfaced two release-gate concerns

Astra correctly stopped its review when the local checkout moved from
`c18a990e371eb391a59320b6853de96e47dddebe` to
`f3d02327a5cb99513a60eeaf14fd517c5e86a09e`. Its reported zero findings are
therefore not a completed review result.

Independent source inspection on current `standalone-dev` confirms both of
Astra's unresolved clues are substantive:

1. Candidate identity can drift during a long-running gate.
   `standalone_s3_live_acceptance.py` captures HEAD once near preflight and
   later promotes the result with that captured SHA. The core final cleanliness
   check only verifies `git status --porcelain`; it does not prove HEAD still
   equals the captured candidate. `standalone_office_soak.py` has the same
   pattern. A clean fast-forward or checkout during the run can therefore leave
   the worktree clean while evidence is attributed to the start SHA. Release
   confidence trusts the stored `candidate_commit`, so it cannot detect a
   mislabeled run afterward.

2. Independent readback proof is weaker than the documented acceptance contract.
   Restart continuity does require an exit-zero write command followed by a later
   readback-shaped command, but the readback is recognized from command text and
   exit status only. A plain `cat` qualifies even though it does not prove the
   trailing newline. The final file bytes are checked separately, which protects
   file-content correctness but does not prove the requested byte-level readback
   actually happened. The post-compaction recovery gate is weaker still: it checks
   validation, some client-tool activity, exact final PASS, command safety, and
   exact final file contents, but does not currently prove an ordered write then
   separate byte-level readback.

These are pending release-gate fixes. Do not continue release evidence
accumulation until they are addressed. The current failed post-compaction trace
should still be inspected before source changes so all known fixes can be batched
into one new candidate.

## 2026-09-22 release-evidence hardening candidate

After Astra quota exhaustion, ChatGPT continued the engineering work directly.

The previous live S3 failure on `f3d02327...` showed repeated successful read-only
client commands followed by a false workspace-inaccessible final. Astra's partial
review also surfaced two independent release-gate integrity gaps.

All three were addressed on `standalone-dev`.

Current exact candidate:

```text
49da82d46d47179aea64dfbf6b7611bdbaa8489d
```

Changes:

```text
1. Recursive-compaction affinity deltas now carry private compacted continuation
   metadata on normal structured tool results as well as generated fallbacks.

2. A post-tool workspace-inaccessible claim is repairable when real workspace-tool
   provenance plus compacted workspace intent are present.

3. Synthetic acceptance readback progress now requires a byte-oriented readback.
   Plain cat/read_text no longer satisfies the byte-level contract.

4. S3 post-compaction recovery now proves:
   successful validation command
   -> successful result write
   -> later separate successful byte-level readback
   -> exact final bytes
   -> exact PASS marker.

5. Effect ordering is based on the last successful write so an earlier readback
   cannot satisfy a later rewrite.

6. Long-running S3, office soak, release-confidence, Desktop E2E, and S4 gates
   re-check candidate identity before PASS evidence is written.
```

Focused regression tests were added/updated for the compacted workspace refusal,
plain-cat rejection, post-last-write byte readback, candidate drift, and structured
affinity metadata.

Standalone CI #894 is the exact-SHA run for this candidate. Earlier intermediate
CI runs from the sequential GitHub edits were cancelled by the workflow concurrency
policy and must not be treated as candidate evidence.

All positive release evidence from older SHAs is historical. Do not start fresh
S3 accumulation until #894 and local deterministic/install gates are green.

## 2026-09-22 focused regression follow-up

The first local focused run on candidate `49da82d...` failed exactly one new
regression:

```text
test_post_tool_workspace_inaccessible_claim_uses_private_compacted_state
```

The implementation carried private compacted metadata correctly, but the compacted
acceptance state did not match the generic workspace-intent classifier because it
used `large_context/result.txt` / `LARGE_CONTEXT_PASS` rather than one of the
older generic workspace keywords. The exact live refusal shape also used
"当前运行环境无法访问 ..." which was narrower than the older refusal patterns.

This was fixed structurally by recognizing the synthetic acceptance result paths
and PASS markers as workspace intent and by recognizing current running/execution
environment path-access refusals.

New exact candidate:

```text
fd1975edf3b90e08faf86d67bdd5967b1ac5130e
```

Exact-SHA Standalone CI is run #895. Local focused/full deterministic gates must
be rerun on this SHA before any S3 evidence is accumulated.

## 2026-09-22 fd1975e candidate deterministic gates green

Exact candidate:

```text
fd1975edf3b90e08faf86d67bdd5967b1ac5130e
```

Candidate-bound local deterministic validation passed:

```text
release-hardening focused: 117 passed, 8 warnings
full suite:                587 passed, 22 warnings
public repository safety: PASS
dependency audit:          PASS
install smoke:             PASS
worktree/final identity:   clean and unchanged
```

The visible browser install-smoke surface also returned `INSTALL_SMOKE_PASS`.

Exact-SHA GitHub Standalone CI #895 completed successfully for the same SHA.

This candidate is now eligible to start fresh S3 evidence accumulation. All S3
success evidence from earlier SHAs remains historical and must not be counted.

## 2026-09-22 first live S3 attempt on fd1975e failed during remote compaction probe

Exact candidate remained:

```text
fd1975edf3b90e08faf86d67bdd5967b1ac5130e
```

The run passed release preflight, repo preflight, local gates, route setup, listener
startup, and restart continuity, then failed before post-compaction recovery:

```text
S3_PHASE=RESTART_CONTINUITY_PASS
FAILURE_CLASS=remote_compaction_probe
FAILURE_DETAIL=rc=1
PRIVATE_EVIDENCE_RECORDED=YES
```

This attempt does not count toward S3 success accumulation. No source change should
be made until the private `remote-compaction-probe.log` and final trigger trace are
inspected. The failure can represent threshold/probe calibration, trigger reply
contract, rollout lifecycle, Remote V2 completion, token-leak guard, or an external
Web failure, and these require different handling.

## 2026-09-22 fd1975e first S3 remote-compaction failure classified as transient pre-submit block

Private coarse-turn trace showed the exact failure:

```text
error: stream disconnected before completion: send_blocked_by_preexisting_generation
turn.failed
agent messages: none
client commands: none
usage: none
```

The browser log showed the guard detected an older generation/stop-state before
submitting the coarse filler and waited for it to end:

```text
[SEND] 发送前检测到页面仍处于旧生成/停止态，等待其结束后再提交本次消息
```

The workflow's terminal-send contract treats
`send_blocked_by_preexisting_generation` as a prompt-filled-but-never-dispatched
failure. Therefore this run did not execute the coarse filler and produced no
workspace/tool side effects. The earlier priority-tier warning is compatibility
noise and not the failure cause.

Classification: transient external/browser-surface pre-submit blocker. Do not
change product source from this single occurrence because the guard behaved
fail-closed and prevented an ambiguous submit. Candidate remains:

```text
fd1975edf3b90e08faf86d67bdd5967b1ac5130e
```

The failed run does not count toward S3 success accumulation. A fresh S3 run on
the unchanged candidate is appropriate after the stale generation has cleared.
If the same preexisting-generation block repeats, investigate bounded safe retry
or explicit external-failure classification without weakening ambiguous-submit
protection.

## 2026-09-22 fd1975e S3 retry failed at restart finalization

Exact candidate remained:

```text
fd1975edf3b90e08faf86d67bdd5967b1ac5130e
```

The retry passed preflight, target reset, route/listener setup, and local gates, then
failed early in restart continuity:

```text
FAILURE_CLASS=restart_resume
FAILURE_DETAIL=final_reply_mismatch
PRIVATE_EVIDENCE_RECORDED=YES
```

The browser-visible final was:

```text
第三步无法在当前执行环境完成验证，因此不能回复 CONTEXT_PASS。
```

This wording is semantically similar to the prior synthetic step-execution stalls,
but it does not name `exec_command`, so the current narrow step-stall matcher may
not recognize it. Do not change source until the restart trace is inspected for
successful validation/write/readback progress. In particular, determine whether
step 3 means the write already succeeded and only byte-level readback remains.

## 2026-09-22 restart step-3 readback stall repaired

Private restart evidence on `fd1975e...` proved:

```text
validation = successful
write = successful
byte readback = missing
result file = exact EMBER-7319 plus trailing LF
final = 第三步无法在当前执行环境完成验证，因此不能回复 CONTEXT_PASS。
```

The final omitted the tool name, so the older narrow numbered-step matcher did
not activate. ChatGPT repaired this structurally using proven acceptance effect
state. When the write is already proven and readback remains incomplete, a
step-3 verification stall referencing the requested PASS contract advances only
to the separate byte-level readback and explicitly forbids rewriting the file.

Premature-PASS detection was also corrected to require readback after the last
successful write rather than after the first write.

The current release candidate is the latest `standalone-dev` head after the
source, regression-test, and release-document commits. All prior candidate-bound
positive evidence is historical and must be regenerated.

## 2026-09-22 77f12c2 candidate deterministic gates green

Exact candidate:

```text
77f12c2374ceeef463a9d245b018a675c68ec053
```

Candidate-bound local validation passed:

```text
acceptance focused:         75 passed
release-hardening focused:  46 passed, 8 warnings
full suite:                 591 passed, 22 warnings
public repository safety:  PASS
dependency audit:           PASS
install smoke:              PASS
final identity/worktree:    clean and unchanged
```

Exact-SHA GitHub Standalone CI #898 also completed successfully for the same SHA:

```text
scaffold-static   PASS
runtime-import    PASS
codex-regression  PASS
release-metadata  PASS
macos-compat      PASS
```

This candidate is now eligible for fresh S3 accumulation. All S3 success evidence
from older SHAs is historical.

## 2026-09-22 bounded safe retry added for repeated pre-submit compaction probe blocks

A later S3 run on `77f12c2...` again stopped at
`remote_compaction_probe rc=1` immediately after restart continuity.

The prior occurrence at this same phase had already been privately proven to be
the exact browser guard condition `send_blocked_by_preexisting_generation` with
no agent message, no tool effect, and no usage record. Because that condition
means the prompt was blocked before model execution, the compaction probe now
contains one bounded continuation-turn retry for that exact evidence shape.

The retry activates only when all of the following are true:

```text
returncode != 0
raw trace contains send_blocked_by_preexisting_generation
no agent messages
no client-tool/file/MCP effects
no input-token usage
no output-token usage
continuation thread_id is present
```

It waits briefly, writes the retry to a separate private trace, and retries the
same prompt once. Any ambiguous partial response, usage evidence, tool effect,
different failure, or second failure remains fail-closed. Seed creation remains
one-shot.

New exact candidate:

```text
20b45ce922e8166b72488c6282e4dca495e9bda0
```

Exact-SHA Standalone CI is run #901. All older candidate-bound evidence is
historical and must not be reused.

## 2026-09-22 20b45ce candidate deterministic gates green

Exact candidate:

```text
20b45ce922e8166b72488c6282e4dca495e9bda0
```

Candidate-bound local validation passed:

```text
compaction-probe focused:  51 passed
acceptance-policy focused: 45 passed
full suite:                594 passed, 22 warnings
public repository safety: PASS
dependency audit:          PASS
install smoke:             PASS
final identity/worktree:   clean and unchanged
```

Exact-SHA GitHub Standalone CI #901 also completed successfully for the same SHA:

```text
scaffold-static   PASS
runtime-import    PASS
codex-regression  PASS
release-metadata  PASS
macos-compat      PASS
```

This candidate is eligible for a fresh S3 attempt. No successful S3 evidence from older SHAs may be counted.

## 2026-09-22 20b45ce first live S3 still failed in remote compaction probe

Exact candidate remained:

```text
20b45ce922e8166b72488c6282e4dca495e9bda0
```

The run again passed restart continuity and then stopped at:

```text
FAILURE_CLASS=remote_compaction_probe
FAILURE_DETAIL=rc=1
PRIVATE_EVIDENCE_RECORDED=YES
```

Because the candidate already contains one bounded retry for the exact
`send_blocked_by_preexisting_generation` no-dispatch shape, do not change source
until the new private probe log and any `*-retry.jsonl` trace are inspected. The
next diagnosis must determine whether the retry activated and the retry itself
failed, or whether this run failed for a different probe reason.

## 2026-09-22 ChatGPT localized Stop false positive confirmed and repaired

Private/live browser logs repeatedly showed the remote-compaction continuation turn
being blocked for the full 300-second pre-fill idle timeout by exactly:

```text
matched_indicator='button[aria-label*="停止"]'
send_stop=False
stop_btn=False
```

The same false positive recurred on the one bounded retry. Both private traces had
zero agent messages, zero tool effects, and zero usage, confirming no prompt was
dispatched.

Root cause: ChatGPT's page-wide generation probe accepted a broad localized
partial aria-label Stop selector even when the matching visible control was not
the active composer generation control.

Repair on `standalone-dev`:

* the probe now records the matched indicator's `data-testid` and whether it is
  inside the active composer rooted at `#prompt-textarea`;
* for ChatGPT only, a broad page-wide Stop aria-label match is ignored when it is
  outside the composer and no stronger generation evidence exists;
* canonical `data-testid="stop-button"`, composer-local Stop, send-as-Stop,
  configured stop/generation selectors, and non-ChatGPT sites remain fail-closed.

Regression tests cover the observed false positive and the strong-evidence cases.

Current exact candidate:

```text
2b5a1772e96e4f6961685757a9cf60aa3b544cc0
```

Exact-SHA Standalone CI is run #904. Older candidate-bound evidence is historical.

## 2026-09-22 2b5a177 candidate deterministic gates green

Exact candidate:

```text
2b5a1772e96e4f6961685757a9cf60aa3b544cc0
```

Candidate-bound local validation passed:

```text
ChatGPT Stop guard focused: 64 passed
acceptance policy focused:  45 passed
full suite:                 597 passed, 22 warnings
public repository safety:  PASS
dependency audit:           PASS
install smoke:              PASS
final identity/worktree:    clean and unchanged
```

Exact-SHA GitHub Standalone CI #904 also completed successfully for the same SHA:

```text
scaffold-static   PASS
runtime-import    PASS
codex-regression  PASS
release-metadata  PASS
macos-compat      PASS
```

This candidate is eligible for a fresh S3 attempt. Older S3 evidence remains historical.

## 2026-09-22 2b5a177 first live S3 reached post-compaction recovery

Exact candidate:

```text
2b5a1772e96e4f6961685757a9cf60aa3b544cc0
```

This run passed:

```text
RESTART_CONTINUITY_PASS
remote compaction probe
180-second compaction cooldown
COMPACTION_COOLDOWN_PASS
```

and then failed at:

```text
FAILURE_CLASS=post_compaction_recovery
FAILURE_DETAIL=final_reply_mismatch
PRIVATE_EVIDENCE_RECORDED=YES
```

This is materially later than the prior pre-fill Stop false-positive failures and
confirms that the localized Stop hardening let the remote-compaction probe
progress.

Do not change source until `post-compaction-recovery.jsonl` is inspected for:
the exact final assistant message, successful workspace-validation command,
result write, separate byte readback, and the final on-disk bytes.

## 2026-09-22 post-compaction recovery completed effects but violated terminal contract

Private post-compaction recovery evidence on `2b5a177...` proved:

```text
workspace validation:              PASS
first result write:                PASS
separate byte-level readback:      PASS
on-disk bytes:                     ORBIT-5921 + trailing LF
extra second result write:         PASS
byte readback after last write:    MISSING
final assistant reply:             descriptive prose, not LARGE_CONTEXT_PASS
```

The exact extra command rewrote `large_context/result.txt` after the successful
byte-level readback and then used only `cat`. The file bytes remained correct,
but the gate correctly invalidated the older readback because acceptance evidence
must follow the last successful write.

Root policy gap: once a synthetic acceptance had completed validation, write, and
a byte-level readback after that write, the tool-calling policy still allowed the
model to emit another exec-like tool call. It also allowed descriptive final prose
instead of the exact requested success sentinel.

Repair on `standalone-dev`:

* synthetic acceptance completion is now explicitly recognized only after
  successful workspace validation plus write plus later byte-level readback;
* once complete, any further exec-like client tool call is intercepted before
  client execution;
* once complete, any final response other than the exact requested
  `CONTEXT_PASS` or `LARGE_CONTEXT_PASS` marker is repaired;
* the repair prompt explicitly forbids further tool calls, rewrites, and
  readbacks and requests only the exact sentinel;
* behavior is scoped to the repository's synthetic acceptance contracts.

Current exact candidate:

```text
c34fcd61478abc73311e42d3f70eb48bb7b7c261
```

Exact-SHA Standalone CI is run #907. Older candidate-bound evidence is historical.

## 2026-09-22 completed-acceptance regression expectation corrected

Local focused validation on `c34fcd6...` found one stale test expectation:

```text
test_acceptance_incomplete_after_write_and_readback_is_not_unfinished
expected should_repair_client_workspace_refusal(...) is False
actual True
```

The implementation behavior is intentional. After validation, write, and later
byte-level readback have completed, `ACCEPTANCE_INCOMPLETE` is no longer an
unfinished-effect signal, but it is still an invalid terminal response because
the synthetic contract requires the exact success sentinel. The regression now
asserts:

```text
looks_like_incomplete_acceptance_continuation(...) == False
looks_like_acceptance_completion_without_exact_sentinel(...) == True
should_repair_client_workspace_refusal(...) == True
```

Only the regression expectation was changed. Current exact candidate:

```text
8cc96f38229d26ff22d124d8ef817bfb9ddde516
```

Exact-SHA Standalone CI is run #908. Candidate-bound validation for the prior SHA
must not be reused.

## 2026-09-22 8cc96f3 candidate deterministic gates green

Exact candidate:

```text
8cc96f38229d26ff22d124d8ef817bfb9ddde516
```

Candidate-bound local validation passed:

```text
acceptance closure focused:      79 passed
compaction/response focused:     30 passed, 8 warnings
full suite:                      601 passed, 22 warnings
public repository safety:        PASS
dependency audit:                PASS
install smoke:                   PASS
final identity/worktree:         clean and unchanged
```

Exact-SHA GitHub Standalone CI #908 also completed successfully for the same SHA:

```text
scaffold-static   PASS
runtime-import    PASS
codex-regression  PASS
release-metadata  PASS
macos-compat      PASS
```

This candidate is eligible for a fresh S3 attempt. No successful S3 evidence from
older SHAs may be counted.

## 2026-09-22/23 S3 success #1 for 8cc96f3 candidate

Exact candidate:

```text
8cc96f38229d26ff22d124d8ef817bfb9ddde516
```

Fresh live S3 success #1 completed with the candidate unchanged and the repository
clean afterward.

Observed local timestamps from the live output:

```text
run start:              2026-09-22 20:30:41 +07
compaction cooldown:    completed by 2026-09-22 21:19:30 +07
final S3 pass:          shortly after 2026-09-22 21:19:35 +07
```

Equivalent UTC evidence window is approximately 2026-09-22 13:30Z through
14:19Z.

Required live markers all passed:

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

S3 candidate-bound success count for this SHA is now 1/3.

Release timing requirement remains: three successes total across at least two
two-hour UTC evidence windows, with at least 7200 seconds from the first success
evidence to the last. Older SHA successes do not count.

## 2026-09-23 S3 attempt #2 failed after compaction recovery turn

Exact candidate remained:

```text
8cc96f38229d26ff22d124d8ef817bfb9ddde516
```

The second fresh live attempt started around 2026-09-23 02:10 +07 and reached:

```text
S3_PHASE=RESTART_CONTINUITY_PASS
S3_PHASE=COMPACTION_COOLDOWN_PASS
```

before failing at:

```text
FAILURE_CLASS=post_compaction_recovery
FAILURE_DETAIL=final_reply_mismatch
PRIVATE_EVIDENCE_RECORDED=YES
```

Do not count this as S3 success #2. S3 success count remains 1/3.

The candidate source must not be changed until the new
`post-compaction-recovery.jsonl` is inspected. Compare its command/effect
sequence with the prior failing run that executed validation, write, byte readback,
then a redundant rewrite. Determine whether the completed-acceptance closure policy
was reached, whether the redundant rewrite was prevented, and what exact final
assistant message was returned.

## 2026-09-23 CLI compatibility strategy pivot

The release strategy is now to absorb current stable Codex CLI compatibility before
publishing the first RC instead of finishing the RC exclusively on the historical
0.153.4 baseline.

Important correction from source review: the standalone bridge already implements
streamed Remote Compaction V2 using trailing `{"type":"compaction_trigger"}` items
on `/v1/responses`, emits one `type=compaction` output item, and carries the
UWA-owned compaction envelope through `encrypted_content`. That support is present
in `app/services/codex_remote_compaction_v2.py` and was originally hardened against
Codex 0.153.4 behavior. The legacy `/v1/responses/compact` route remains only as a
compatibility path and should not be mistaken for the active V2 implementation.

Therefore the next compatibility target should be the current stable Codex CLI
0.156.0 rather than stopping at 0.155.1. Keep 0.153.4 as the known-good compatibility
floor while validating 0.156.0 as the new release baseline.

Before changing CLI, preserve the failed S3 #2 private trace as a 0.153.4 comparison
fixture. After the CLI changes, all release-candidate live evidence must be regenerated
and must record the exact CLI version as part of the environment identity.

The local Mac currently also requires acceptance of the Xcode/Apple SDK license;
the diagnostic shell reached the worktree check and was blocked by xcodebuild before
completion.

## 2026-09-23 local Codex installation source confirmed before 0.156 migration

Primary Codex executable is the NVM/npm installation:

```text
/Users/jerson/.nvm/versions/node/v24.18.0/bin/codex
@openai/codex@0.153.4
node v24.18.0
npm 11.16.0
```

A second lower-priority executable also exists at:

```text
/Users/jerson/.local/bin/codex
```

Homebrew Codex is not installed. The current Homebrew cask metadata reports
0.155.1, so Homebrew should not be introduced for this migration.

Migration plan: upgrade the existing npm installation in place to Codex CLI 0.156.0,
verify every visible `codex` executable and PATH resolution, and preserve an exact
rollback command to npm 0.153.4. Once the CLI changes, candidate live evidence must
be regenerated with the exact CLI version recorded.

## 2026-09-23 Codex CLI 0.156.0 installed and S3 baseline bound

Primary selected CLI now reports:

```text
/Users/jerson/.nvm/versions/node/v24.18.0/bin/codex
codex-cli 0.156.0
@openai/codex@0.156.0
```

A stale lower-priority standalone installation remains at:

```text
/Users/jerson/.local/bin/codex
codex-cli 0.148.0
```

It is currently shadowed by the NVM/npm path and has not been deleted.

The public `standalone-dev` branch now binds release S3 evidence to Codex CLI
0.156.0. The runner parses the selected `codex --version`, rejects any other
version, prints `S3_CODEX_CLI_VERSION=0.156.0`, records the version in successful
private result evidence, and re-checks the version before pass promotion.

Current exact source candidate after the baseline binding/documentation commits:

```text
1543a28ffcfb9cc639d9db0fbe60fd8974c92f57
```

All older candidate-bound local/CI/S3 evidence is historical and must not count
toward the 0.156.0 release baseline.

## 2026-09-23 0.156 deterministic gate exposed package-import defect

The first local 0.156 compatibility gate did not reach protocol execution. Pytest
collection failed while importing:

```text
tests/test_codex_remote_compaction_trigger_probe.py
ModuleNotFoundError: No module named 'codex_auto_compact_trigger_probe'
```

Root cause: several tools relied on direct-script sibling imports. That works when
Python executes a file from `tools/`, because that directory is put on
`sys.path`, but fails when pytest imports the same module as
`tools.codex_remote_compaction_trigger_probe`.

The three compaction probe modules now support both forms:

```text
package import:  from . import sibling
direct script:   fallback to import sibling
```

Files changed:

```text
tools/codex_remote_compaction_trigger_probe.py
tools/codex_auto_compact_trigger_probe.py
tools/codex_large_context_live.py
```

This is an import/packaging regression in the release tooling, not yet evidence of
a Codex 0.156 wire/protocol incompatibility.

Current exact candidate:

```text
96157a51979815b5a2e2e57b258339fedac73748
```

All candidate-bound evidence from `1543a28...` is superseded.

## 2026-09-23 0.156 deterministic compatibility gates green on 96157a5

Exact candidate:

```text
96157a51979815b5a2e2e57b258339fedac73748
```

Local validation under Codex CLI 0.156.0 passed:

```text
package import smoke:                PASS
remote compaction V2:               26 passed
response/continuation contract:     79 passed, 8 warnings
CLI baseline gate:                  33 passed
full suite:                         604 passed, 22 warnings
public repository safety:           PASS
dependency audit:                   PASS
install smoke:                      PASS
final repo/CLI identity:            PASS
```

This is the first deterministic evidence that the 0.156.0 baseline is compatible
with the current streamed Remote Compaction V2 and continuation contract at the
test-suite level.

Exact-SHA Standalone CI #914 is still running at the time of this handoff update.
Current observed state: `scaffold-static=PASS`, `runtime-import=in_progress`.
Do not count CI as green until all jobs complete successfully.

## 2026-09-23 Codex 0.156 real-route smoke and exact-SHA CI green

Exact candidate:

```text
96157a51979815b5a2e2e57b258339fedac73748
```

Real CLI smoke under Codex CLI 0.156.0 passed through the configured UWA route:

```text
thread count:             1
real exec_command count:  1
command exit:             0
final assistant reply:    CODEX_0156_TOOL_PASS
terminal event:           turn.completed
CODEX_0156_REAL_TOOL_SMOKE=PASS
repository remained clean
```

The CLI also emitted the known non-fatal warning that service tier `priority` is
not advertised for model `chatgpt`; it was omitted and the request completed
normally.

Exact-SHA Standalone CI #914 has now completed successfully for the same SHA:

```text
scaffold-static   PASS
runtime-import    PASS
codex-regression  PASS
release-metadata  PASS
macos-compat      PASS
```

This candidate is now ready for the first full S3 live run under the 0.156.0
release baseline. S3 success count for this baseline is 0/3 before that run.

## 2026-09-23 Codex 0.156 S3 success #1 on 96157a5

Exact candidate:

```text
96157a51979815b5a2e2e57b258339fedac73748
```

The first full S3 live run under the Codex CLI 0.156.0 release baseline passed.
The runner printed the bound environment identity:

```text
S3_CODEX_CLI_VERSION=0.156.0
```

and all release-critical live markers passed, including restart continuity,
native auto-compaction, Remote V2 compaction, post-compaction recovery, real
client tool execution, route verification, request-manager cleanup, and final
repository cleanliness.

Final marker:

```text
STANDALONE_S3=PASS_LIVE_CLOSED
```

Observed run start was 2026-09-23 03:39:15 +07, equivalent to
2026-09-22 20:39:15Z. This falls in the UTC two-hour bucket beginning 20:00Z.

S3 success count for the Codex 0.156.0 / 96157a5 release baseline is now 1/3.
The release-confidence implementation buckets by the private result directory
start timestamp using `floor(epoch_seconds / 7200)`.

## 2026-09-23 Codex 0.156 S3 attempt #2 failed in restart resume

Exact candidate remained:

```text
96157a51979815b5a2e2e57b258339fedac73748
```

CLI identity remained:

```text
codex-cli 0.156.0
```

The second S3 attempt reached local gates and the restart-continuity phase, then
failed before a successful resumed turn completed:

```text
FAILURE_CLASS=restart_resume
FAILURE_DETAIL=rc=1
PRIVATE_EVIDENCE_RECORDED=YES
```

Do not count this as S3 success #2. The 0.156 baseline remains 1/3.

This failure class differs from the prior post-compaction final-reply mismatches.
The runner raises `restart_resume rc=1` only when the real resumed Codex CLI
process itself exits non-zero. No source change should be made until the latest
private `restart-resume.jsonl` and bounded UWA log metadata are inspected.

## 2026-09-23 review of isolated restart-resume fix branch

Fix branch:

```text
codex/0156-restart-resume-fix
91a6fa7a03317c46248af6da7984a9892ea198ed
```

It is exactly one commit ahead of `standalone-dev` candidate
`96157a51979815b5a2e2e57b258339fedac73748` and is not merged.

Changed files are limited to:

```text
app/api/codex_responses_v2.py
app/services/client_tool_policy.py
tests/test_client_tool_policy_repeated_refusal.py
tests/test_codex_responses_v2_contract.py
```

Static review found the change direction appropriately scoped to synthetic
`CONTEXT_PASS` / `LARGE_CONTEXT_PASS` acceptance progress. It carries only
adapter-generated marker/path/effect booleans as private policy metadata on
affinity deltas and tests that this metadata is not browser-visible. After a
proven write, text-only termination is forced toward the required separate byte
readback; after readback, the existing exact-sentinel closure still applies.

No new private trace/thread/timestamp path markers were found in the changed
files. Existing synthetic test strings containing a local-looking path predate
this branch.

Do not merge yet. Next gate is a targeted live restart/resume reproduction on
this branch, followed by focused/full tests and preferably PR CI before changing
the canonical candidate.
