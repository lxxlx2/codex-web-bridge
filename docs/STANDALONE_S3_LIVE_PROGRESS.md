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
