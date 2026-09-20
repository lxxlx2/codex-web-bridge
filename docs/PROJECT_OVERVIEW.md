# Project overview

## Core goal

Codex Web Bridge has one narrow job:

> route Codex Desktop / Codex CLI model inference through a logged-in ChatGPT Web session while keeping all local workspace authority inside the Codex client.

The bridge exists so a normal Codex workflow can continue to use local files, shell commands, edits, tests, Git, sandboxing, and approval controls while model inference is transported through ChatGPT Web.

It is not a general browser-agent platform, a provider router, or a replacement for Codex's local execution model.

## System boundary

```text
Codex Desktop / CLI
  owns:
    workspace
    shell
    edits
    tests
    Git
    sandbox
    approvals
        |
        | Responses API + client function tools
        v
Codex Web Bridge
  owns:
    protocol compatibility
    ChatGPT Web routing
    continuation
    compaction
    browser lifecycle
    sanitized local bridge state
        |
        v
logged-in ChatGPT Web
  owns:
    model inference only
```

A ChatGPT Web page never receives direct shell or filesystem authority from this project.

When model reasoning requires a local action, the expected path is:

```text
assistant function_call
-> Codex client executes locally
-> function_call_output
-> bridge continues the same logical turn
```

## Supported release path

The first public RC supports one inference backend:

```text
Codex -> Codex Web Bridge -> ChatGPT Web
```

There is no automatic fallback to another provider, a local model, or an official API in v0.1.0-rc.1.

If the controlled ChatGPT Web path is unavailable, rate-limited, ambiguous, not logged in, or cannot safely continue, the bridge must stop with an explicit failure. Silent route substitution would make release evidence and workspace behavior harder to reason about, so it is intentionally out of scope for this RC.

## Reliability model

The project does not treat a single successful live run as proof of production reliability.

A release candidate must combine:

- deterministic unit and regression coverage;
- exact-SHA CI;
- repeated full S3 live passes on the same candidate;
- office-like client-tool soak coverage with independent postcondition checks;
- Codex Desktop E2E;
- clean-checkout install / rollback smoke;
- S4 release consistency;
- main-branch CI;
- tagged-source smoke.

See [RELIABILITY_MODEL.md](RELIABILITY_MODEL.md) and [TESTING.md](TESTING.md).

The important distinction is:

```text
Bridge correctness:
  Did the protocol, tool call, continuation, route and lifecycle behave safely?

Task correctness:
  Did the model choose the right command or edit for the user's real work?
```

The bridge can enforce and verify many protocol and side-effect invariants, but it cannot make arbitrary model reasoning infallible.

## Failure behavior

The default rule is fail closed.

Examples:

- browser/CDP unavailable -> stop;
- wrong or ambiguous ChatGPT surface -> stop;
- auth/challenge -> stop;
- rate limit / quota -> stop;
- route mismatch -> stop;
- uncertain tool side effect -> do not blindly replay;
- generation terminal state cannot be proven -> stop;
- candidate-bound release evidence does not match current Git HEAD -> stop.

A clear external failure does not automatically mean the candidate source is defective, but it also does not count as positive release evidence.

## Public support surface

Publicly supported concepts are deliberately small:

- local loopback API;
- Codex Responses compatibility;
- ChatGPT Web inference route;
- real Codex client tools;
- same-thread continuation;
- restart continuity;
- native / Remote V2 compaction;
- lifecycle commands:
  - `codex-uwa`
  - `codex-uwa-status`
  - `codex-uwa-stop`
  - `codex-official`

Inherited generic runtime code that remains in the repository for dependency closure is not automatically part of the supported product surface.

## Repository map

```text
app/
  api/        Responses and standalone API boundary
  core/       browser workflow, streaming and generation lifecycle
  services/   tool policy, affinity, compaction, route/runtime behavior

tools/
  install/lifecycle helpers
  deterministic audits
  live acceptance gates
  release gates

tests/
  deterministic regression and gate-orchestration coverage

docs/
  durable architecture, testing, maintenance and release policy

manifests/
  extraction/provenance records
```

Start with:

- [ARCHITECTURE.md](ARCHITECTURE.md) for code ownership;
- [MAINTAINER_HANDOFF.md](MAINTAINER_HANDOFF.md) for change/debug workflow;
- [../tests/README.md](../tests/README.md) for test ownership;
- [../tools/README.md](../tools/README.md) for operational tooling;
- [RELEASE_PROCESS.md](RELEASE_PROCESS.md) for publishing.

## Non-goals for the first RC

The first RC does not attempt to provide:

- automatic fallback providers;
- local-model fallback;
- official-API fallback;
- quota or rate-limit bypass;
- account rotation;
- public remote API exposure by default;
- direct ChatGPT Web filesystem/shell access;
- Windows/Linux release-blocking live certification;
- broad provider support inherited from Universal Web API.

These can be reconsidered later only as explicit new product requirements.
