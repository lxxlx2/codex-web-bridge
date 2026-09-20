# Standalone S2 runtime seam checkpoint

> Historical engineering evidence. This file preserves the state and reasoning from its recorded stage; current release status is determined by exact-candidate gates. See [docs/README.md](README.md) for the current documentation map.\n\n
Date: 2026-09-10

## Scope

This checkpoint narrows the standalone import/runtime boundary without changing the validated Codex browser protocol behavior.

The integrated source baseline remains pinned to:

```text
lxxlx2/universal-web-api@a140002e65a02a3323abcde3e1fdb8674710c996
```

## Completed extraction

`app/api/codex_runtime.py` now owns the Codex-facing Responses request model, request-to-chat conversion, response-object conversion, in-process Responses state, completion/error normalization, and the narrow backing-worker entrypoint.

`app/api/codex_compact.py` consumes those standalone protocol helpers directly.

The validated generic chat implementation has been preserved unchanged as `app/api/legacy_chat_runtime.py`. `app/api/chat.py` is now a lightweight compatibility facade. It exports the standalone protocol symbols immediately and enters the preserved legacy worker only when an execution-only symbol is actually called.

`app/core/parsers` now eagerly registers only `ChatGPTParser`; historical provider parser exports remain lazy during S2 compatibility work.

## Import-side-effect diagnostic

A new CI assertion required `import main` to complete without loading `app.api.legacy_chat_runtime`.

The first run failed because Python import introspection reached the compatibility module's `__getattr__`, which loaded the legacy module even for dunder lookups. The facade was tightened so dunder lookups raise `AttributeError` without entering the compatibility runtime.

The corrected checkpoint passes both Standalone CI jobs:

```text
scaffold       PASS
runtime-import PASS
```

The runtime-import job installs the candidate dependencies, imports the actual standalone application, verifies the required Codex route surface, rejects generic API route leakage, verifies that the preserved legacy chat runtime is absent from `sys.modules` after startup, and runs the focused standalone regression set.

## Current boundary

Startup and route registration are now independent of the large legacy chat runtime. The remaining S2 execution dependency is explicit: `codex_runtime._run_chat_completion_final()` still enters the preserved browser worker when a real ChatGPT Web request is executed.

That execution seam remains intentionally preserved until an extracted Codex-only ChatGPT executor has parity coverage for request lifecycle, tool-calling round trips, cancellation, browser/session ownership and non-stream result normalization.

## Next gate

Extract the Codex-only ChatGPT execution path behind a focused executor module, prove parity against the preserved implementation under mocks/regression tests, switch the standalone backing-worker entrypoint to it, then verify that a synthetic execution path no longer imports `app.api.legacy_chat_runtime`.

The preserved legacy runtime remains a rollback/reference boundary until those checks and the complete Codex regression suite pass. It is not yet a deletion candidate for the release branch.
