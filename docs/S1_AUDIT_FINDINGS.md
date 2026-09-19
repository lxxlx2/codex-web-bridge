# S1 dependency/import/runtime audit findings

Source baseline: `lxxlx2/universal-web-api@a140002e65a02a3323abcde3e1fdb8674710c996`.

The S1 audit combines a static local-import closure, import-only runtime tracing, symbol-level slicing of the shared `app/api/chat.py` Responses path, non-Python asset scanning and public-repository safety checks.

## Current evidence

The integration tree contains 297 Python files. The conservative Codex bridge seed set contains 25 explicit core files. The integration-tree static closure reaches 143 Python files and import-only runtime tracing loads 165 local Python files. Forty-six validation files were identified as useful for standalone release work. Seventy-six Python files were initially classified as exclusion candidates before S2 deletion-safety proof.

The source requirements file contains 15 direct entries. The source bridge closure sees 14 external import roots, while runtime import tracing naturally sees a larger transitive dependency set.

## Main coupling findings

Two package side effects accounted for a large amount of artificial coupling:

1. `app/api/__init__.py` imported `app.api.routes` at package-import time. That route aggregator pulled unrelated generic API surfaces such as Anthropic, browser/config/system/tab/command/provider routes into the static and runtime closure.
2. `app/core/parsers/__init__.py` imported and registered every built-in provider parser at package-import time. The Codex path reached the parser package through the generic network-monitor/runtime stack, loading unrelated provider parsers as side effects.

S2 narrowed both boundaries and validated the resulting Codex-only startup graph in standalone CI.

## Shared chat runtime

The source baseline reused a subset of `app/api/chat.py` for Responses request models, conversion, result construction, backing ChatGPT-Web execution, state persistence and auth. Symbol-level analysis confirmed this file as a major shared-runtime coupling point.

S2 extracted the Responses/runtime seam, ChatGPT Web executor and standalone Responses fallback, then removed the legacy generic chat runtime after frozen-contract parity tests replaced the old legacy-module test oracle.

## Dependency implications

The source integration closure reached `DrissionPage`, Pillow, BeautifulSoup, FastAPI, Pydantic, requests, jsonschema, psutil, pyperclip and platform/runtime helpers. The standalone dependency set is now audited against the extracted tree rather than inferred from the larger integration source.

## Non-Python assets

The conservative source scan identified browser/site/config JSON assets and several dynamic/private runtime paths. The bootstrap copied public config candidates required by the extracted tree and recorded them in the candidate manifest. Private runtime state remains outside the repository.

## S1 closure

S1 is PASS / CLOSED. Its source-baseline, import/runtime, asset, dependency and provenance evidence was sufficient to drive S2 extraction. S2 subsequently proved the extracted tree independently and is also PASS / CLOSED.

The current post-S2 dependency evidence and final deletion tranche are recorded in `docs/STANDALONE_S2_CLOSURE_2026-09-10.md`. S3 live parity is the current release gate.