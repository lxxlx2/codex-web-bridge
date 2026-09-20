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

## Current live S3 blocker

Latest S3 run:

```text
FAILURE_CLASS=restart_resume
DETAIL=final_reply_mismatch
```

Read-only private evidence established the exact sequence:

```text
workspace validation: completed, exit 0
result write:         completed, exit 0
result file:          exact expected token + trailing LF
separate readback:    missing
turn terminal:        completed
assistant final:      ACCEPTANCE_INCOMPLETE
trace error:          none
```

The S3 gate correctly failed.

## Root cause

The client workspace repair policy already handles narrowly scoped synthetic acceptance failures such as:

```text
premature CONTEXT_PASS / LARGE_CONTEXT_PASS
ACCEPTANCE_WORKSPACE_MISMATCH
false client-tool unavailability
compacted missing-task/state-only completion
```

It currently does not treat exact final text:

```text
ACCEPTANCE_INCOMPLETE
```

as an unfinished synthetic acceptance continuation.

In the observed live run, validation and write were complete, while the mandatory separate readback remained unfinished. The text response was therefore accepted as a normal final response and S3 later rejected it.

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
