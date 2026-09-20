# Architecture

## Purpose

Codex Web Bridge translates Codex Desktop / CLI model requests into a ChatGPT Web-backed Responses-compatible flow while preserving a strict authority boundary:

```text
Codex Desktop / CLI
  owns workspace, shell, edits, tests, Git, sandbox, approvals
        |
        | Responses API / function calls
        v
Codex Web Bridge
  owns protocol compatibility, Web routing, continuation, compaction,
  browser lifecycle, and sanitized runtime state
        |
        | controlled browser interaction
        v
logged-in ChatGPT Web session
```

The browser is not given direct filesystem or shell authority.

The first RC has one supported inference backend: ChatGPT Web. The architecture intentionally does not add an automatic provider/local-model/API fallback. If the controlled Web path cannot continue safely, the request fails explicitly. This keeps route evidence, continuation state, and side-effect reasoning attributable to one backend.

## Primary request path

The main standalone request path is:

```text
main.py
  -> app/api/standalone_routes.py
  -> app/api/codex_responses_v2.py
  -> app/services/codex_chatgpt_executor.py
  -> app/services/tool_calling.py
  -> app/core/browser / app/core/workflow
  -> ChatGPT Web

If the model requests a local tool:
  Codex client executes it
  -> function_call_output
  -> app/api/codex_runtime.py normalization
  -> continuation / affinity / tool policy
  -> same logical turn continues
```

### Entrypoints

- `main.py`: FastAPI application, health, lifespan, standalone router.
- `start.py`: local launcher, virtualenv/bootstrap handling, loopback boundary.
- `app/api/standalone_routes.py`: binds only the standalone Codex-compatible API surface.

### Responses and continuation

- `app/api/codex_responses_v2.py`: primary Responses V2 request handling, browser delta construction, strict required-tool flow, affinity-aware execution.
- `app/api/codex_runtime.py`: Responses request models/normalization and tool-result conversion.
- `app/services/codex_responses_state.py`: private continuation state.
- `app/services/codex_web_session_affinity.py`: binds response/history identity to a verified ChatGPT conversation.

### Client-tool authority

- `app/services/codex_chatgpt_executor.py`: executes one ChatGPT-backed inference round.
- `app/services/tool_calling.py` and `tool_calling_*.py`: parse, validate, and continue tool-call round trips.
- `app/services/client_tool_policy.py`: repairs contradictions such as a model claiming a declared client workspace tool is unavailable after real tool evidence proves otherwise.

A valid local-tool path is:

```text
assistant function_call
  -> Codex client local execution
  -> function_call_output
  -> same turn continues
```

Text that merely imitates a tool call is not accepted when a real client tool is required.

### Compaction and long context

- `app/services/codex_remote_compaction_v2.py`: Remote V2 compaction envelope, lineage, durable/active state merge, bounded Web backing flow.
- native auto-compaction remains client-driven;
- Remote V2 compaction is bridge-aware and preserves lineage;
- post-compaction tool results may carry private internal provenance so the bridge can continue an unresolved workspace task without replaying a side effect.

The key invariant is that a completed local tool is reused only when its thread/user-turn/compaction lineage can be proven.

### Browser lifecycle

- `app/core/generation_state.py`: shared selectors for active-generation state.
- `app/core/stream_monitor.py`: determines when a Web response is truly terminal.
- `app/core/workflow/executor_send.py`: pre-send idle guard and send-state checks.
- `app/services/chatgpt_web_surface.py`: sanitized Chat/Work/blocker classification.
- `app/services/chatgpt_web_rate_limit_guard.py`: explicit rate-limit handling.
- `app/services/request_manager.py`: request lifecycle, cancellation, terminal cleanup, sanitized monitoring.

Stream completion and pre-send guards intentionally share generation-state selectors. A localized Stop button must not be visible to one guard but invisible to the other.

## Release and acceptance tooling

The release path is implemented as ordinary versioned Python tools rather than undocumented operator steps:

- `tools/standalone_s3_live_acceptance.py`: synthetic continuity/compaction stress;
- `tools/standalone_office_soak.py`: safe office-like client-tool workflows with independent effect checks;
- `tools/standalone_release_confidence.py`: candidate-bound repeated-live evidence aggregation;
- `tools/standalone_desktop_e2e_gate.py`: real Codex Desktop path;
- `tools/standalone_install_smoke.py`: clean install, lifecycle, rollback;
- `tools/standalone_s4_release_gate.py`: release-tree/evidence consistency;
- `tools/standalone_tagged_source_smoke.py`: final tagged-source verification.

These tools store raw live evidence under `~/.uwa` and write only sanitized result markers. See [../tools/README.md](../tools/README.md).

The office acceptance fixtures live under an isolated synthetic workspace. Their checkers verify actual files, changed-path scope, tests, command history, and exact output rather than accepting assistant prose as proof of completion.

## State and privacy

Public repository state:

- reusable source code;
- generic configuration defaults;
- tests and sanitized acceptance contracts;
- release policy and historical engineering decisions.

Private local state:

```text
~/.uwa/
```

Examples include acceptance traces, continuity evidence, local result files, runtime metadata, and browser/session details.

Raw prompts, command bodies, tool output, cookies, browser profiles, conversation URLs, and raw thread/session identifiers must not be committed.

## Compatibility facades and inherited runtime

Some files are intentionally compatibility facades:

- `app/core/browser.py` -> `app/core/browser/`
- `app/core/tab_pool.py` -> `app/core/tab_pool_parts/`
- `app/core/config.py` -> `app/core/config_parts/`
- `app/services/config_engine.py` -> `app/services/config/`

The standalone repository was conservatively extracted from a larger Universal Web API runtime. Several large generic browser/config/media modules remain because static/runtime closure and live parity proved them part of the current safe dependency boundary.

Their presence does not mean every upstream provider or feature is part of the supported Codex Web Bridge product surface.

Large-scale runtime slimming is intentionally deferred until after the first stable release. See [ROADMAP.md](ROADMAP.md).

## Safe extension points

Changes are usually lower risk when they stay within one of these boundaries:

- protocol normalization: `app/api/codex_*.py`;
- Codex policy: `app/services/codex_*.py`, `client_tool_policy.py`;
- ChatGPT surface/readiness: `app/services/chatgpt_web_*.py`;
- acceptance harnesses: `tools/standalone_*.py`;
- focused regression tests in `tests/`.

High-risk changes include:

- stream terminal-state logic;
- pre-send lifecycle and duplicate-send protection;
- required-tool replay semantics;
- compaction lineage;
- affinity identity;
- request-manager cleanup;
- browser target selection;
- security defaults.

Those changes require focused regression plus full-suite testing, and may require candidate-bound live acceptance before release.

## Release evidence architecture

Release acceptance intentionally uses independent evidence:

```text
CI/non-live
  proves deterministic regression and static safety

S3 live
  proves restart + native/remote compaction + post-compaction recovery
  + route + request cleanup

Codex Desktop E2E
  proves real Desktop same-thread context + real local tools

install smoke
  proves clean checkout, wrappers, switch, rollback, auth preservation

S4
  proves exact-candidate evidence consistency, docs, version, security,
  provenance, install, S3, and Desktop candidate match
```

No historical PASS transfers automatically to a different commit.
