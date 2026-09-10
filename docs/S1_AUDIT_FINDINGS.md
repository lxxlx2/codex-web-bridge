# S1 dependency/import/runtime audit findings

Source baseline: `lxxlx2/universal-web-api@a140002e65a02a3323abcde3e1fdb8674710c996`.

The S1 audit combines a static local-import closure, import-only runtime tracing, symbol-level slicing of the shared `app/api/chat.py` Responses path, non-Python asset scanning and public-repository safety checks.

## Current evidence

The integration tree contains 297 Python files. The conservative Codex bridge seed set contains 25 explicit core files. The integration-tree static closure reaches 143 Python files and import-only runtime tracing loads 165 local Python files. Forty-six validation files are currently useful for standalone release work. Seventy-six Python files are already classified as exclusion candidates, although S2 still has to prove deletion safety on the extracted tree.

The current production requirements file contains 15 direct entries. The static bridge closure sees 14 external import roots, while runtime import tracing naturally sees a larger transitive dependency set.

## Main coupling findings

Two package side effects account for a large amount of artificial coupling:

1. `app/api/__init__.py` imports `app.api.routes` at package-import time. That route aggregator pulls unrelated generic API surfaces such as Anthropic, browser/config/system/tab/command/provider routes into the static and runtime closure. Codex remote-compaction reaches this package through `from app.api import codex_responses_v2`.
2. `app/core/parsers/__init__.py` imports and registers every built-in provider parser at package-import time. The Codex path reaches the parser package through the generic network-monitor/runtime stack, which loads unrelated provider parsers as side effects.

These are S2 decoupling targets. The preferred fix is to narrow imports and registration boundaries rather than carry every generic provider into the standalone repository.

## Shared chat runtime

Codex currently reuses a subset of `app/api/chat.py` for Responses request models, conversion, result construction, backing ChatGPT-Web execution, state persistence and auth. Symbol-level analysis confirms this file is a major shared-runtime coupling point.

S2 should extract the selected Responses/chat symbols into a narrow bridge runtime module and leave the broad generic chat route behind once parity tests confirm the split.

## Dependency implications

The integration closure currently reaches `DrissionPage`, Pillow, BeautifulSoup, FastAPI, Pydantic, requests, jsonschema, psutil, pyperclip and platform-specific/runtime helpers. Some direct requirements such as `reportlab` and Windows clipboard support appear because generic integration-tree paths are still coupled in.

S2 must regenerate the dependency set after router/parser/chat decoupling. Packages are removed only when the standalone import graph and CI/live parity show they are no longer needed.

## Non-Python assets

The conservative source scan finds browser/site/config JSON assets and several dynamic/private runtime paths. The bootstrap copies the public config candidates needed for the first extracted tree and records them in the candidate manifest. Static dashboard/UI assets are not automatically treated as release requirements; S2 parity determines whether any are actually needed.

## S1 to S2 handoff

S1 has enough evidence to start the conservative extraction in this repository. S1 remains open until the bootstrapped standalone tree is available and its actual import/runtime graph can be compared with the integration-tree audit. S2 then removes generic surfaces incrementally with CI evidence after each decoupling step.
