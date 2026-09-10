# Codex Web Bridge

[中文说明](README.zh-CN.md)

Codex Web Bridge is an unofficial local bridge for routing Codex Desktop/CLI model requests through ChatGPT Web while preserving local client-side tool execution.

> Status: standalone extraction and release hardening in progress on `standalone-dev`. The validated integrated implementation already passed its M1-M7 release gates in `lxxlx2/universal-web-api`; this repository is the cleaner standalone extraction and is not yet tagged as a release.

## Design

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

The browser does not receive direct filesystem authority. Local tools continue to execute in the Codex client under its own sandbox and approval policy.

## Validated integrated baseline

The source baseline for the first standalone extraction is pinned to:

```text
lxxlx2/universal-web-api@a140002e65a02a3323abcde3e1fdb8674710c996
```

The integrated V2 baseline passed protocol/CLI acceptance, real client-tool round trips, same-thread and restart continuity, native/remote compaction, Desktop acceptance, cancellation cleanup, final regression, public-repository safety and merge-to-main gates.

## Standalone release path

```text
S1 dependency/import/runtime audit          in progress
S2 standalone extraction and decoupling     next
S3 CI + CLI/Desktop/live parity             pending
S4 first standalone release                 pending
```

Development happens on `standalone-dev`. The default branch remains a release boundary until the standalone acceptance gate is complete.

## Bootstrap the conservative S2 candidate

The repository contains a guarded extractor that copies a conservative candidate tree from the validated source baseline. It computes the local Python import closure from Codex bridge entry points, includes known import-time side-effect modules, release-validation tests and required configuration candidates, then records the source baseline and copied-file manifest.

```bash
python3 tools/bootstrap_from_uwa.py --commit --push
```

The resulting tree is intentionally larger than the final release. S2 removes generic Universal Web API coupling only after tests prove the narrower tree remains correct.

## Planned standalone surfaces

The release candidate is expected to keep the Codex Responses bridge, ChatGPT Web transport, Web mode/model verification, local-client-tool protocol, continuation persistence, Web conversation affinity, remote compaction, stream compatibility, provider switching/lifecycle helpers, release validation and the minimal browser/config runtime they genuinely require.

Broad generic-provider APIs, dashboards, unrelated parser/provider registries, updater surfaces and historical milestone tooling are candidates for removal when standalone parity proves they are unnecessary.

## Security defaults

The release target keeps conservative local defaults:

```text
API bind       127.0.0.1
remote access  disabled by default
CORS           disabled by default
unsafe Python  disabled
private state  under ~/.uwa
```

Do not commit credentials, cookies, browser profiles, private prompts, command/tool bodies, private Responses persistence, raw browser/session identifiers or full wire traces.

See [SECURITY.md](SECURITY.md) for the disclosure and local-safety policy.

## License and attribution

This standalone project is derived from `lumingya/universal-web-api` through the validated `lxxlx2/universal-web-api` integration tree. Upstream-derived portions remain under the GNU Affero General Public License v3.0 and applicable copyright notices.

See [NOTICE.md](NOTICE.md) for provenance details. The full AGPL-3.0 text is copied from the validated source tree during bootstrap and must remain present in release candidates.

## Unofficial project notice

This is an independent interoperability and engineering project. It is not an official OpenAI, ChatGPT or Codex product and does not imply partnership, authorization or endorsement. It does not alter third-party account entitlements, subscription limits, quotas or model availability. Users are responsible for complying with applicable software, website and service terms and laws.
