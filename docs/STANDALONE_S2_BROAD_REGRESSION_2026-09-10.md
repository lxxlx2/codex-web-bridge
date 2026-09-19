# Standalone S2 broad regression checkpoint — 2026-09-10

## Status

The extracted standalone ChatGPT executor has passed the broad non-live Codex regression gate on `standalone-dev`.

The successful Standalone CI checkpoint contains three green jobs:

- `scaffold`
- `runtime-import`
- `codex-regression`

The runtime-import job continues to prove that the standalone application exposes the required Codex endpoints, does not expose the generic UWA admin/provider route surface, does not load `app.api.legacy_chat_runtime` during startup, and binds the canonical Responses, compact and V2 backing execution paths to `app.services.codex_chatgpt_executor.execute_chatgpt_nonstream`.

The broad non-live regression job now covers the standalone Codex, client-tool-policy, ChatGPT-Web preparation/mode, command-installation and security suites.

## Intentional exclusions

Three historical integration tests are excluded from this ordinary S2 CI gate for explicit scope reasons:

1. `tests/test_codex_m5_stage_af_replay.py` requires the integrated M5 final-regression runner chain from `universal-web-api`. That chain validates the historical integrated release and is not part of the standalone runtime.
2. `tests/test_codex_remote_compaction_recovery.py` depends on a previously created private compacted Codex thread and is a live acceptance harness.
3. `tests/test_codex_remote_compaction_recovery_staged.py` has the same private-thread/live requirement.

These exclusions do not waive the corresponding behavior. Remote-compaction and same-thread recovery remain S3 live-acceptance requirements for the standalone release candidate.

## Security launcher alignment

The historical security test expected helper functions from the integrated upstream launcher. The standalone launcher intentionally does not contain that updater/proxy bootstrap API. The regression now validates the standalone boundary directly: repository-local environment setup plus loopback-only service binding, with generic upstream launcher helpers absent.

## S2 next gate

The standalone candidate is still conservatively oversized. The next S2 step is evidence-backed pruning:

1. build a deterministic static local-import closure from the actual standalone entrypoints and execution seams;
2. compare that closure with modules loaded by a clean standalone startup;
3. classify unreachable generic UWA routers, provider implementations, command/dashboard/update code and parser families;
4. remove only evidence-backed candidates in bounded tranches;
5. rerun all three Standalone CI jobs after every tranche;
6. regenerate the direct dependency set only after the runtime tree has been reduced.

The preserved legacy chat runtime remains a temporary parity/rollback reference during this pruning phase. It is not an active standalone startup dependency.
