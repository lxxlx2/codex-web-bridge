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

## Current canonical candidate before the next source fix

```text
90cdbdfb7b8259f8fb00e7a0e35b57c26f7ba711
```

Deterministic validation on that candidate was green, GitHub exact-SHA CI was green, and clean install/rollback smoke passed.

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

## Next engineering step

Implement the narrowest safe repair on `standalone-dev`.

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
