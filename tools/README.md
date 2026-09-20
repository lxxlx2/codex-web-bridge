# Tooling guide

The tools directory contains developer utilities, lifecycle commands, private
acceptance harnesses, and release gates. Public users normally need only the
installed `codex-uwa` lifecycle commands.

## User-facing lifecycle

```text
tools/install_codex_uwa_commands.py
tools/codex_provider_switch.py
tools/codex_uwa_lifecycle.py
```

Installed commands:

```bash
codex-uwa
codex-uwa-status
codex-uwa-stop
codex-official
```

These commands manage the standalone bridge route and listener. They do not
provide an automatic alternate inference backend.

## Deterministic repository checks

```text
public_repo_safety_check.py
standalone_dependency_audit.py
```

Run on every release candidate:

```bash
.venv/bin/python tools/public_repo_safety_check.py
.venv/bin/python tools/standalone_dependency_audit.py --check
```

## Acceptance workspace

`codex_desktop_acceptance.py` creates an isolated synthetic workspace under
`~/uwa-codex-acceptance`.

Scenarios:

| Scenario | What it proves |
| --- | --- |
| `context` | same-thread recall plus exact result-file verification |
| `multi_file` | multi-file edits, tests, and changed-path scope |
| `failure_recovery` | real failing run before the fix, then passing rerun |
| `git_diff` | requirements-driven edit and Git diff discipline |
| `interactive` | long-running process and stdin continuation |

The checker validates real filesystem/Git effects rather than trusting the
assistant's final text.

## Live acceptance

### S3

```bash
.venv/bin/python tools/standalone_s3_live_acceptance.py
```

Purpose:

- restart continuity;
- real client tools;
- native/Remote V2 compaction;
- post-compaction recovery;
- route evidence;
- cleanup.

Raw evidence stays private under `~/.uwa/standalone-s3`.

### Office-work soak

```bash
.venv/bin/python tools/standalone_office_soak.py
```

Purpose:

- exercise safe office-like workflows through real Codex client tools;
- independently verify their side effects;
- stop immediately on a failed live turn;
- never switch to an alternate provider.

Raw evidence stays private under `~/.uwa/standalone-office-soak`.

### Desktop E2E

```bash
.venv/bin/python tools/standalone_desktop_e2e_gate.py prepare
# perform the printed Codex Desktop steps
.venv/bin/python tools/standalone_desktop_e2e_gate.py verify
```

Purpose:

- real Desktop same-thread context;
- local file/shell behavior;
- route verification.

## Release confidence

After the exact candidate has accumulated the required successful live evidence:

```bash
.venv/bin/python tools/standalone_release_confidence.py
```

It requires:

```text
>= 3 S3 PASS_LIVE_CLOSED results on current HEAD
>= 2 two-hour UTC evidence windows
>= 7200 seconds first-to-last successful S3 span
STANDALONE_OFFICE_SOAK=PASS on current HEAD
```

It does not rerun ChatGPT Web. It only validates candidate-bound private result
markers.

## Install / rollback smoke

```bash
.venv/bin/python tools/standalone_install_smoke.py
```

Purpose:

- clean checkout behavior;
- dependency bootstrap;
- installed wrappers;
- listener ownership;
- basic Codex request;
- official rollback;
- authentication preservation.

## S4 release gate

```bash
.venv/bin/python tools/standalone_s4_release_gate.py
```

S4 binds the release tree and private release evidence to the current Git HEAD.
It checks:

- docs/version/security/provenance;
- release confidence;
- install smoke;
- latest S3 candidate match;
- Desktop E2E candidate match.

## Tagged-source smoke

After the tag exists, run from a fresh checkout of the tag:

```bash
.venv/bin/python tools/standalone_tagged_source_smoke.py
```

This is the final source-tree check before creating the GitHub Release.

## Exact release order

```text
focused tests
full suite
public safety + dependency audit
exact-SHA CI
clean install/rollback smoke
repeated S3 passes
office-work soak
release confidence
Desktop E2E
S4
fast-forward main
main CI
tag
tagged-source smoke
GitHub Release
```

If a source or release-document commit changes the candidate SHA, regenerate the
candidate-bound evidence required by the release policy.

## Safety

Acceptance tools may create only their documented private/synthetic state.

Do not modify them to:

- upload private prompts or tool output;
- store cookies/browser profiles in the repository;
- bypass rate limits;
- automatically rotate accounts;
- replay uncertain side-effecting tools;
- silently route failed ChatGPT Web requests to another provider.

For architecture and maintenance context, see
[../docs/MAINTAINER_HANDOFF.md](../docs/MAINTAINER_HANDOFF.md).
