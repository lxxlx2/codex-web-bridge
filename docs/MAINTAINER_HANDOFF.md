# Maintainer handoff

This guide is for a contributor taking over Codex Web Bridge without needing to read the historical acceptance documents line by line.

## Read these first

1. [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)
2. [ARCHITECTURE.md](ARCHITECTURE.md)
3. [RELIABILITY_MODEL.md](RELIABILITY_MODEL.md)
4. [TESTING.md](TESTING.md)
5. [../tests/README.md](../tests/README.md)
6. [../tools/README.md](../tools/README.md)
7. [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

The release-specific policy is in [RELEASE_PROCESS.md](RELEASE_PROCESS.md).

## Product invariants

Do not weaken these to make a test pass.

### Local authority

ChatGPT Web performs inference only.

```text
function_call
-> Codex client
-> local execution / sandbox / approval
-> function_call_output
-> continuation
```

The bridge must not silently execute a user's workspace command itself.

### Single inference route for rc.1

The supported release route is:

```text
provider=uwa
model=chatgpt
effort=high
backend=ChatGPT Web
```

If that route cannot continue safely, stop with an explicit failure. Do not silently substitute another provider, a local model, or an official API.

### Side-effect uncertainty

A client tool whose execution state is unknown must not be blindly replayed.

A later model statement that a currently declared `exec_command` is unavailable is contradictory and may be repaired, but the repair still emits a normal client tool call. It does not execute the command inside the bridge.

### Web surface

Before sending, the controlled page must be a unique usable Chat surface with an empty composer and no rate-limit/quota/auth/challenge blocker.

### Terminal generation

The bridge must not report a turn as complete while the Web page still exposes an active generation/Stop state.

### Candidate identity

Live evidence is valid only for the exact candidate commit recorded in the private result.

## Code ownership map

| Concern | Primary files |
| --- | --- |
| standalone API boundary | `main.py`, `app/api/standalone_routes.py` |
| Responses normalization | `app/api/codex_runtime.py` |
| V2 Responses / strict tool flow | `app/api/codex_responses_v2.py` |
| Web-backed Codex execution | `app/services/codex_chatgpt_executor.py` |
| tool parsing / retries | `app/services/tool_calling*.py` |
| workspace-tool contradiction policy | `app/services/client_tool_policy.py` |
| runtime continuation hardening | `app/services/codex_v2_runtime_hardening.py` |
| Remote V2 compaction | `app/services/codex_remote_compaction_v2.py` |
| Web conversation affinity | `app/services/codex_web_session_affinity.py` |
| generation state | `app/core/generation_state.py` |
| stream terminal detection | `app/core/stream_monitor.py` |
| pre-send guard | `app/core/workflow/executor_send.py` |
| Web surface classification | `app/services/chatgpt_web_surface.py` |
| rate-limit handling | `app/services/chatgpt_web_rate_limit_guard.py` |
| request lifecycle | `app/services/request_manager.py` |
| release acceptance | `tools/standalone_*.py` |

## Test ownership map

Use [../tests/README.md](../tests/README.md) for the complete map.

High-value starting points:

```text
client tool refusal / provenance
  tests/test_client_tool_policy*.py
  tests/test_codex_required_tool_continuation_patch.py

continuation / affinity
  tests/test_codex_web_session_affinity.py
  tests/test_codex_v2_runtime_hardening.py

generation / send lifecycle
  tests/test_stream_monitor_terminal_state.py
  tests/test_chatgpt_web_*.py

compaction
  tests/test_codex_remote_compaction*.py
  tests/test_codex_large_context_acceptance.py

release gates
  tests/test_codex_standalone_s3_runner.py
  tests/test_standalone_office_soak.py
  tests/test_standalone_release_confidence.py
  tests/test_standalone_desktop_e2e_gate.py
  tests/test_standalone_install_smoke.py
  tests/test_standalone_s4_release_gate.py
  tests/test_standalone_tagged_source_smoke.py
```

## Debugging rule

Do not rerun a long live gate immediately after failure.

Classify first.

```text
deterministic local failure
  -> fix focused code/test
  -> focused tests
  -> full suite

live product failure
  -> inspect private sanitized evidence
  -> narrow root cause
  -> fix
  -> regenerate affected candidate evidence

external Web failure
  -> no source change unless evidence shows a bridge defect
  -> wait for condition to clear
  -> new live attempt later
```

Examples of external conditions include rate limit, quota, login interruption, challenge page, or temporary Web availability.

## Private evidence locations

```text
~/.uwa/standalone-s3/
~/.uwa/standalone-office-soak/
~/.uwa/standalone-release-confidence/
~/.uwa/standalone-desktop-e2e/
~/.uwa/standalone-s4/
~/.uwa/debug/codex-wire/
```

Do not copy raw private traces into GitHub issues or commits.

For public diagnosis, record only:

- candidate SHA;
- sanitized failure class;
- sanitized phase marker;
- pass/fail counters;
- relevant non-sensitive environment information.

## Release branch discipline

Normal development remains on `standalone-dev`.

A temporary hardening branch may be used for a coordinated release-preparation batch. Before live release evidence:

1. deterministic validation on the hardening branch;
2. review the complete diff;
3. merge/fast-forward into `standalone-dev`;
4. freeze the resulting candidate SHA;
5. generate live evidence on that exact candidate.

The S3 live runner intentionally expects the canonical release-candidate branch rather than a temporary work branch.

## Safe change workflow

For a normal bug:

```text
read code + existing tests
-> reproduce deterministically when possible
-> add/update focused regression
-> implement narrow fix
-> focused tests
-> full suite
-> safety/dependency audits
-> assess which candidate-bound gates are invalidated
```

Avoid opportunistic module moves in the same change as a browser, continuation, or tool-protocol bug.

## Repository structure policy

The current release keeps the runtime/test/tool paths stable to minimize import and operator breakage.

Clarity is provided by:

- this handoff map;
- `tests/README.md`;
- `tools/README.md`;
- narrow module ownership docs;
- descriptive test names.

Large physical directory moves belong in a separately tested structural change after release unless they are required for correctness.

## Release confidence

Before S4, the exact candidate needs:

```text
>= 3 full S3 PASS_LIVE_CLOSED results
>= 2 two-hour UTC evidence windows
STANDALONE_OFFICE_SOAK=PASS
STANDALONE_RELEASE_CONFIDENCE=PASS
STANDALONE_DESKTOP_E2E=PASS
INSTALL_SMOKE=PASS
```

Then S4 binds those results to the current HEAD.

See [RELIABILITY_MODEL.md](RELIABILITY_MODEL.md) for rationale.
