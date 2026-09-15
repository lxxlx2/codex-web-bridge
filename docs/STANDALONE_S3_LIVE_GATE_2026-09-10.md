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

## Gate state

```text
S1 dependency / import / runtime audit       PASS / CLOSED
S2 extraction / decoupling / minimal tree    PASS / CLOSED
S3 CI + CLI/Desktop/live parity              CURRENT / LIVE RUN READY
S4 release candidate / first release         PENDING
```

S3 must remain open until the standalone live runner completes successfully. No release tag is created before that result is recorded and the S4 release-candidate checks are prepared.
