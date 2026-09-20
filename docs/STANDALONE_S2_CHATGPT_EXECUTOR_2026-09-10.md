# Standalone S2 ChatGPT executor checkpoint

> Historical engineering evidence. This file preserves the state and reasoning from its recorded stage; current release status is determined by exact-candidate gates. See [docs/README.md](README.md) for the current documentation map.\n\n
Date: 2026-09-10

## Status

The standalone runtime now binds Codex Responses execution to `app.services.codex_chatgpt_executor.execute_chatgpt_nonstream`.

The binding is applied to the canonical Responses runtime and to the compact and V2 modules that import the backing executor by value. The preserved generic UWA chat implementation remains in `app/api/legacy_chat_runtime.py` only as a parity and rollback reference during S2.

## Execution boundary

The extracted executor selects the controlled `chatgpt.com` browser route directly. It retains the request-manager lifecycle, cancellation propagation, tracked blocking-worker cleanup, browser workflow execution and tool-calling repair flow required by Codex Desktop/CLI. Client tools remain client-owned: the bridge returns model function calls and does not execute local workspace commands itself.

Responses `text.format` behavior is preserved by applying the integrated baseline JSON-object and JSON-schema prompt contracts before browser execution. The extracted helper is covered against the pinned integrated baseline.

## CI evidence

Standalone CI now proves in a fresh Python process that:

- the standalone application imports successfully with the required Codex routes;
- generic provider/admin route prefixes are absent;
- `app.api.legacy_chat_runtime` is not imported by standalone startup;
- the canonical runtime, compact path and V2 path all point at the extracted ChatGPT executor.

Focused executor regression covers route pinning, normal request lifecycle completion, caller-cancellation propagation, tool-call return behavior and response-format/error parity. The checkpoint CI completed successfully after these gates were added.

## Remaining work

S2 is still open. Before the legacy runtime can be removed, the extracted executor must receive broader parity coverage and the complete Codex regression suite must pass against the standalone tree. Dependency and file pruning follows test-backed proof that the new execution path no longer requires the generic UWA runtime graph.

S3 real Codex CLI/Desktop/live parity has not started. No release should be created from this checkpoint.
