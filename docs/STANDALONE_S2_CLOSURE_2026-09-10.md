# Standalone S2 extraction closure

> Historical engineering evidence. This file preserves the state and reasoning from its recorded stage; current release status is determined by exact-candidate gates. See [docs/README.md](README.md) for the current documentation map.\n\n
Date: 2026-09-10

Source baseline: `lxxlx2/universal-web-api@a140002e65a02a3323abcde3e1fdb8674710c996`.

S2 is closed for the standalone candidate. The extracted tree now exposes a Codex-only FastAPI entrypoint, owns the Responses protocol/runtime seam, routes ChatGPT Web backing execution through `app/services/codex_chatgpt_executor.py`, owns the generic Responses fallback in `app/api/standalone_responses_backing.py`, and no longer carries the legacy generic chat runtime.

## Final pruning tranche

The dependency audit identified ten files outside both the static runtime closure and startup-loaded set. Nine runtime-unreachable generic/development files were removed:

- `app/api/legacy_chat_runtime.py`
- `app/api/tab_routes.py`
- `app/core/workflow_editor.py`
- `app/services/catalog_routing.py`
- `app/services/text_filter.py`
- `app/utils/model_routing.py`
- `app/utils/similarity.py`
- `update_preserve.py`
- `updater.py`

`security_guard.py` is intentionally retained even though it is outside the runtime import closure. It is part of the public-repository/release safety gate, so its presence is policy-required rather than a runtime dependency.

The first deletion commit correctly failed closed because two tests still imported the removed legacy module as a parity oracle. Those tests were converted to frozen protocol/format contracts captured from the validated integrated baseline. The replacement tests also assert that `app.api.legacy_chat_runtime` is absent from the standalone tree.

## Green post-prune evidence

Standalone CI run 196 completed successfully on the repaired pruning tree:

- `scaffold`: PASS
- `runtime-import`: PASS
- `codex-regression`: PASS
- focused standalone regression: 24 passed
- `STANDALONE_RUNTIME_IMPORT=PASS`
- `LEGACY_CHAT_STARTUP_IMPORT=NO`
- `CODEX_CHATGPT_EXECUTOR_BINDING=PASS`
- `STANDALONE_DEPENDENCY_AUDIT=PASS`

The post-prune dependency report is:

```text
RUNTIME_PYTHON_MODULE_COUNT=143
STATIC_CLOSURE_COUNT=137
STARTUP_LOADED_LOCAL_COUNT=119
STATIC_UNREACHABLE_COUNT=6
PRUNE_CANDIDATE_COUNT=1
OBVIOUS_GENERIC_CANDIDATE_COUNT=0
NON_CHATGPT_PARSER_CANDIDATE_COUNT=0
STARTUP_FORBIDDEN_LOADED=NONE
EXPECTED_STARTUP_MISSING=NONE
STARTUP_NON_CHATGPT_PARSERS=NONE
PRUNE_CANDIDATE=security_guard
```

The remaining configuration, tab-pool, browser-workflow and command-engine modules are inside the conservative static closure and are treated as required upstream runtime for this release candidate. S3 live parity is the next authority for whether any further runtime slicing is safe.

## Gate state

```text
S1 dependency / import / runtime audit       PASS / CLOSED
S2 extraction / decoupling / minimal tree    PASS / CLOSED
S3 CI + CLI/Desktop/live parity              CURRENT
S4 release candidate / first release         PENDING
```

No release tag should be created until S3 completes on the standalone repository itself.