# Codex Web Bridge

[中文](README.md) · [English](README.en.md) · [ไทย](README.th.md) · [日本語](README.ja.md) · [한국어](README.ko.md)

Codex Web Bridge is an unofficial local bridge that routes Codex Desktop / Codex CLI model requests through a logged-in ChatGPT Web session while keeping file access, shell commands, edits, tests, Git operations, sandboxing, and approvals under the Codex client.

> Current status: S1 and S2 are closed. `standalone-dev` is in S3 standalone CLI/Desktop/live parity acceptance. S4, the first standalone release, remains blocked until S3 is fully closed.
>
> Latest S3 checkpoint: restart continuity, native auto-compaction, Remote V2 compaction, and required-tool completion across compaction lineage have been proven on the real path. The remaining blocker is post-compaction workspace validation. In the latest recovery turn Codex issued a real client-side `exec_command`, but it executed only `pwd` instead of the complete marker and `large_context` directory check required by the prompt, so the model returned `ACCEPTANCE_WORKSPACE_MISMATCH`. The acceptance workspace, marker, and `large_context` directory were independently confirmed to exist. S3 is not closed yet.

## Quick start

Development currently happens on `standalone-dev`. After the first release, `main` and release tags will be the stable boundary.

```bash
git clone https://github.com/lxxlx2/codex-web-bridge.git
cd codex-web-bridge
git switch standalone-dev
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

## Core boundaries

1. The Codex client remains the local execution authority. The bridge does not bypass the client to modify the workspace directly.
2. Provider, model, and reasoning effort must be verified through configuration, session metadata, and wire evidence.
3. A textual imitation of a tool call does not count when a real client tool is required. Acceptance requires a real `function_call -> local execution -> function_call_output` round trip.
4. Same-thread continuation, UWA restart, Web conversation affinity, and native/remote compaction must preserve logical continuity and fail closed when correctness cannot be proven.
5. Local tools are not blindly replayed when side-effect state is uncertain.
6. Public repository data excludes private prompts, command bodies, tool output, cookies, browser profiles, and full wire traces.

## S3 acceptance progress

```text
S1 dependency / import / runtime audit           PASS / CLOSED
S2 standalone extraction and decoupling          PASS / CLOSED
S3 CI + Codex CLI / Desktop / live parity        CURRENT
S4 first standalone release                      PENDING
```

Already proven on the standalone live path:

```text
repository / local safety gates                  PASS
UWA route = uwa / chatgpt / high                 PASS
real client exec_command round trip               PASS
same-thread continuity after UWA restart          PASS
native auto-compaction trigger                   PASS
Remote V2 compaction route + completion          PASS
required-tool completion across compaction       PASS
request-manager cleanup / healthy listener       PASS
```

Still open:

```text
post-compaction full recovery                    OPEN
STANDALONE_S3=PASS_LIVE_CLOSED                   NOT YET
```

The current failure has moved past earlier issues around compaction triggering, repeated compaction, empty output, and required-tool replay. The latest recovery command was `/bin/zsh -lc pwd` in the correct acceptance workspace, but the model did not complete the remaining marker and directory checks contained in the same required-tool instruction, so the gate correctly failed closed.

S4 will not start until the full live gate reports:

```text
S3_POST_COMPACTION_RECOVERY=PASS
S3_ROUTE_UWA_CHATGPT_HIGH=PASS
S3_REQUEST_MANAGER_CLEAN=PASS
S3_REPOSITORY_CLEAN_AFTER_LIVE=PASS
STANDALONE_S3=PASS_LIVE_CLOSED
```

## Continuity and long context

The implementation covers `previous_response_id`, call-id continuity, Web conversation affinity, private persisted continuity state, native auto-compaction, and Remote V2 compaction.

Remote V2 compaction uses a controlled envelope with an internal compaction lineage. Required-tool completion is reused only when it can be tied to the same compaction lineage and user turn. This prevents a completed local tool from being forced again after compaction removes function-call history, while avoiding cross-thread state contamination.

Long-context limits are still development-time implementation details and may change as Codex and ChatGPT Web behavior changes.

## Validated integrated baseline

The first standalone extraction is pinned to:

```text
lxxlx2/universal-web-api@a140002e65a02a3323abcde3e1fdb8674710c996
```

That integrated baseline passed Stage A-F protocol/CLI acceptance, real client-tool round trips, same-thread and restart continuity, native/remote compaction, Desktop acceptance, stream cancellation cleanup, final regression, and M1-M7 integrated release gates.

The standalone repository must still complete its own S3. Historical results from the integrated repository are not treated as standalone release evidence.

## Development and release

Development happens on `standalone-dev`; `main` remains the release boundary. The first planned candidate is:

```text
v0.1.0-rc.1
```

Only after independent S3 live parity, safety checks, dependency/provenance audit, and release artifact validation will the project move to:

```text
v0.1.0
```

## Security and privacy

Conservative release defaults:

```text
API bind       127.0.0.1
remote access  disabled by default
CORS           disabled by default
unsafe Python  disabled
private state  ~/.uwa
```

Do not commit credentials, cookies, browser profiles, private prompts, command/tool bodies, private Responses persistence, raw browser/session identifiers, or full wire traces.

See [SECURITY.md](SECURITY.md) for the disclosure and local-safety policy.

## License and attribution

This project is derived from [lumingya/universal-web-api](https://github.com/lumingya/universal-web-api) through the validated `lxxlx2/universal-web-api` integration tree. Upstream-derived code remains subject to the GNU Affero General Public License v3.0 and applicable copyright notices.

See [NOTICE.md](NOTICE.md) for provenance details and [LICENSE](LICENSE) for the full license text.

## Unofficial project notice

Codex Web Bridge is an independent interoperability, learning, and engineering project. It is not an official OpenAI, ChatGPT, or Codex product and does not imply partnership, authorization, endorsement, or approval by OpenAI or any third party.

The project does not alter or bypass account entitlements, subscription limits, quotas, model permissions, or platform safety controls. Users are responsible for complying with applicable software, website, service terms, organizational policy, and law, and for the local commands and code changes they choose to execute.
