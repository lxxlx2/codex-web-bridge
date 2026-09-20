# Codex Web Bridge

[中文](README.md) · [English](README.en.md) · [ไทย](README.th.md) · [日本語](README.ja.md) · [한국어](README.ko.md)

Codex Web Bridge is an unofficial local bridge with one narrow goal: route Codex Desktop / Codex CLI model inference through a logged-in ChatGPT Web session while keeping file access, shell commands, edits, tests, Git operations, sandboxing, and approvals entirely under the Codex client.

The first RC supports one inference path:

```text
Codex Desktop / CLI -> Codex Web Bridge -> ChatGPT Web
```

There is no automatic fallback to another provider, a local model, or an official API in this RC. If ChatGPT Web, the account quota, the controlled browser surface, or route safety cannot be proven, the bridge fails explicitly and stops instead of silently switching backends.

> The first RC uses an exact-candidate release policy: CI, S3 live, Codex Desktop E2E, clean-install smoke, and the S4 release gate must all bind to the same commit. A historical PASS does not transfer automatically to a new code or documentation commit.
>
> The repository now includes a complete release/acceptance workflow. Start with the [project overview](docs/PROJECT_OVERVIEW.md). Contributors and maintainers should also use [CONTRIBUTING.md](CONTRIBUTING.md), [docs/README.md](docs/README.md), and [docs/MAINTAINER_HANDOFF.md](docs/MAINTAINER_HANDOFF.md).

## Quick start

The first RC is live-certified primarily on macOS. Runtime requirements are Python 3.10+, Codex Desktop/CLI, and a Chromium-compatible browser reachable through local CDP with a logged-in ChatGPT Web session. The default CDP port is `9222`.
The bridge attaches to an already running browser and does not launch it automatically; see [docs/BROWSER_SETUP.md](docs/BROWSER_SETUP.md) for first-time setup.

Regular users should install from `main` or a Release tag. Contributors use `standalone-dev`.

```bash
git clone https://github.com/lxxlx2/codex-web-bridge.git
cd codex-web-bridge
python3 tools/install_codex_uwa_commands.py
export PATH="$HOME/bin:$PATH"
```

Switch Codex to Web Bridge:

```bash
codex-uwa
```

Restore the official Codex route:

```bash
codex-official
```

Check status:

```bash
codex-uwa-status
```

Stop the local bridge:

```bash
codex-uwa-stop
```

Default local endpoint:

```text
http://127.0.0.1:8199
```

Health check:

```bash
curl -sS http://127.0.0.1:8199/health
```

The first start may create the project virtual environment and install dependencies. If browser/CDP, ChatGPT login state, or the controlled Web surface is not safe for input, the bridge fails closed rather than silently sending to the wrong page.

## Architecture

```text
Codex Desktop / CLI
  owns workspace, shell, edits, tests, Git, sandbox and approvals
        |
        v
Codex Web Bridge
  owns Responses compatibility, routing, continuity, compaction and browser transport
        |
        v
logged-in ChatGPT Web session
```

The browser never receives direct filesystem authority. When a real local tool is required, the bridge returns a standard Responses `function_call`; the Codex client executes it locally and sends the resulting `function_call_output` back into the same turn.

Current controlled UWA route:

```text
provider = uwa
model = chatgpt
reasoning effort = high
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the primary call path, continuation/affinity/compaction design, compatibility facades, and retained upstream runtime.

## Core boundaries

1. The Codex client remains the local execution authority. The bridge does not bypass the client to modify the workspace directly.
2. Provider, model, and reasoning effort must be verified through configuration, session metadata, and wire evidence.
3. A textual imitation of a tool call does not count when a real client tool is required. Acceptance requires a real `function_call -> local execution -> function_call_output` round trip.
4. Same-thread continuation, UWA restart, Web conversation affinity, and native/remote compaction must preserve logical continuity and fail closed when correctness cannot be proven.
5. Local tools are not blindly replayed when side-effect state is uncertain.
6. Public repository data excludes private prompts, command bodies, tool output, cookies, browser profiles, raw conversation/thread/session identifiers, conversation URLs, and full wire traces.
7. Tracked `config/` contains reusable project defaults only; machine-specific route groups, tab exclusions, and remembered conversation state stay out of Git.

## RC acceptance requirements

All release evidence for the first RC must bind to the same candidate commit, and one lucky live run is not enough for release confidence:

```text
S1 / S2                                         PASS / CLOSED
standalone deterministic regression             PASS
exact-SHA CI                                    PASS
clean-checkout install / rollback smoke         PASS
S3 full live PASS_LIVE_CLOSED                   >= 3 times, same SHA
successful S3 evidence windows                  >= 2 two-hour UTC windows
office-work soak + effect verification          PASS, same SHA
release confidence aggregate                    PASS, same SHA
Codex Desktop E2E                               PASS, same SHA
S4 docs/version/security/provenance              PASS, same SHA
main CI                                         PASS BEFORE TAG
tagged-source smoke                             PASS BEFORE GITHUB RELEASE
```

S3 proves restart continuity, native/remote compaction, post-compaction recovery, route verification, and cleanup. The office-work soak exercises multi-file edits, real failure recovery, Git diff discipline, and interactive processes while independent checkers verify actual files/tests/diffs instead of trusting final model prose. Desktop E2E covers the real desktop path.

An external ChatGPT Web rate limit/quota/auth/challenge makes the current live run fail explicitly and stop. That does not automatically prove a source-code defect, but it also does not count toward the required successful evidence.

See [docs/TESTING.md](docs/TESTING.md) and [docs/RELIABILITY_MODEL.md](docs/RELIABILITY_MODEL.md).

## Continuity and long context

The implementation covers `previous_response_id`, call-id continuity, Web conversation affinity, private persisted continuity state, native auto-compaction, and Remote V2 compaction.

Remote V2 compaction uses a controlled envelope with an internal compaction lineage. Required-tool completion is reused only when it can be tied to the same compaction lineage and user turn. This prevents a completed local tool from being forced again after compaction removes function-call history, while avoiding cross-thread state contamination.

Long-context limits remain implementation details and may change as Codex and ChatGPT Web behavior changes.

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for an index of historical live failures, root causes, and protecting regressions.

## Validated integrated baseline

The first standalone extraction is pinned to:

```text
lxxlx2/universal-web-api@a140002e65a02a3323abcde3e1fdb8674710c996
```

That integrated baseline passed Stage A-F protocol/CLI acceptance, real client-tool round trips, same-thread and restart continuity, native/remote compaction, Desktop acceptance, stream cancellation cleanup, final regression, and M1-M7 integrated release gates.

Those historical results are provenance/design evidence only. Every standalone release candidate regenerates release evidence on its own exact commit.

Some browser/config/media runtime remains from the larger upstream tree because dependency/runtime closure and live parity still require it. Its presence does not make every upstream provider a supported Codex Web Bridge surface. See [docs/ROADMAP.md](docs/ROADMAP.md) for the post-stable slimming plan.

## Development and release

Normal development happens on `standalone-dev`; `main` is the release boundary and Release tags are immutable public checkpoints. The first planned candidate is:

```text
v0.1.0-rc.1
```

After the RC is published, the project enters an observation/compatibility period. Source changes before stable use a newer RC suffix. When no release blocker remains, the project moves to:

```text
v0.1.0
```

Contributors should start with [CONTRIBUTING.md](CONTRIBUTING.md). New maintainers should read [docs/MAINTAINER_HANDOFF.md](docs/MAINTAINER_HANDOFF.md). Local setup/configuration is documented in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md); the test and tool maps are [tests/README.md](tests/README.md) and [tools/README.md](tools/README.md).

See [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) for the RC platform, browser/CDP, account-limit, and retained-runtime constraints.

## Security and privacy

Conservative release defaults:

```text
API bind       127.0.0.1
remote access  disabled by default
CORS           disabled by default
unsafe Python  disabled
private state  ~/.uwa
```

Do not commit credentials, cookies, browser profiles, private prompts, command/tool bodies, private Responses persistence, raw conversation/thread/session identifiers, conversation URLs, or full wire traces.

See [SECURITY.md](SECURITY.md) for the disclosure and local-safety policy.

## License and attribution

This project is derived from [lumingya/universal-web-api](https://github.com/lumingya/universal-web-api) through the validated `lxxlx2/universal-web-api` integration tree. Upstream-derived code remains subject to the GNU Affero General Public License v3.0 and applicable copyright notices.

See [NOTICE.md](NOTICE.md) for provenance details and [LICENSE](LICENSE) for the full license text.

## Unofficial project notice

Codex Web Bridge is an independent interoperability, learning, and engineering project. It is not an official OpenAI, ChatGPT, or Codex product and does not imply partnership, authorization, endorsement, or approval by OpenAI or any third party.

The project does not alter or bypass account entitlements, subscription limits, quotas, model permissions, or platform safety controls. Users are responsible for complying with applicable software, website, service terms, organizational policy, and law, and for the local commands and code changes they choose to execute.
