# Codex Desktop E2E Release Gate

This gate exists because the automated S3 live runner intentionally keeps Codex Desktop quiet and drives the Codex CLI. That isolation is required for deterministic continuity, compaction, route, and cleanup evidence, but CLI evidence alone does not prove the final Codex Desktop product path.

For `v0.1.0-rc.1`, release acceptance therefore has two complementary live gates:

1. `standalone_s3_live_acceptance.py`: unattended CLI protocol/continuity/compaction acceptance.
2. `standalone_desktop_e2e_gate.py`: real Codex Desktop project/tool/continuity/route acceptance.

Both results are candidate-SHA bound and both are required by the S4 release gate.

## Why Desktop is kept quiet during S3

Codex Desktop and Codex CLI share Codex configuration, UWA listener state, ChatGPT Web transport, and route/session evidence. Running both concurrently would make it difficult to attribute requests, tool calls, compaction events, and cleanup to one controlled test. S3 therefore temporarily closes Desktop when it was running and restores the prior Desktop-running state afterward.

## Desktop gate workflow

The Desktop gate is intentionally operator-assisted. The repository does not use brittle macOS Accessibility/UI scripting to type into Codex Desktop. The gate automates preparation and verification while the three synthetic prompts are sent through the real Desktop UI.

Before starting, ChatGPT Web must be a safe ordinary Chat surface. Work, quota exhaustion, usage exhaustion, rate limiting, auth/challenge, dirty composer, and ambiguous target states fail closed before the Desktop run starts.

Prepare:

```bash
.venv/bin/python tools/standalone_desktop_e2e_gate.py prepare
```

The command:

- requires a clean/current `standalone-dev` checkout;
- configures `provider=uwa`, `model=chatgpt`, `reasoning=high`;
- starts/validates the standalone listener;
- requires a clean ChatGPT Web surface;
- prepares `~/uwa-codex-acceptance`;
- records a private route-audit marker;
- opens Codex Desktop on the acceptance workspace;
- prints the exact synthetic prompts to run.

Run the first two context prompts in the same Desktop thread. Run the multi-file prompt in a fresh Desktop thread.

Then verify:

```bash
.venv/bin/python tools/standalone_desktop_e2e_gate.py verify
```

A PASS proves:

```text
STANDALONE_DESKTOP_E2E=PASS
DESKTOP_CONTEXT=PASS
DESKTOP_LOCAL_TOOLS=PASS
DESKTOP_ROUTE_UWA_CHATGPT_HIGH=PASS
DESKTOP_REQUEST_MANAGER_CLEAN=PASS
candidate_commit=<current HEAD>
```

The private result is stored at:

```text
~/.uwa/standalone-desktop-e2e/result.txt
```

Status-only inspection does not send a model request:

```bash
.venv/bin/python tools/standalone_desktop_e2e_gate.py status
```

## Release rule

The S4 release gate requires all of the following evidence to match the same frozen candidate SHA:

- full S3 live PASS;
- real Codex Desktop E2E PASS;
- clean-checkout install/rollback smoke PASS.

A Web rate limit or quota state is an external blocker. Do not repeatedly rerun S3 or Desktop E2E while the passive surface status remains blocked.
