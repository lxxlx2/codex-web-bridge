# Release process

GitHub Releases are the public, immutable distribution checkpoints for Codex Web Bridge. A Release is created from an exact Git tag and is separate from ordinary development commits on `standalone-dev`.

## Version policy

The first standalone candidate will use:

```text
v0.1.0-rc.1
```

If further release-candidate fixes are required, increment the RC suffix. The first stable standalone release will use:

```text
v0.1.0
```

Patch-only fixes then use `v0.1.x`; larger compatible feature work may move to `v0.2.0`.

## Release gate

Do not create a GitHub Release from the current extraction branch. A tag is publishable only after all of the following are true:

1. S1 dependency/import/runtime audit is closed.
2. S2 standalone extraction and decoupling is closed.
3. S3 unit/regression CI plus real Codex CLI/Desktop/live parity is PASS.
4. Public-repository safety, provenance, LICENSE/NOTICE and dependency checks are PASS.
5. The release tree is clean and `main` points to the exact validated candidate commit.
6. The main-branch CI run for that exact commit is green.
7. `VERSION`, `CHANGELOG.md`, README status and release notes agree with the tag.
8. A fresh checkout of the tag passes the documented tagged-source smoke before the GitHub Release is published.

## Planned release contents

Each Release should identify the exact commit and verified environment, summarize user-visible changes and known limitations, and publish integrity metadata for any generated archive or installer. GitHub automatically provides source-code ZIP and tar.gz snapshots for the tagged commit.

The project may later add generated convenience bundles and SHA-256 checksums, but those artifacts must be produced from the tagged `main` commit and must not contain browser profiles, cookies, credentials, private Responses state, prompts, tool bodies, wire traces or other local state.

## Current state

`standalone-dev` is the development/candidate branch and `main` is the release boundary. A release commit is publishable only when CI, S3 live closure, Desktop E2E, clean-install smoke, and S4 all bind to that exact commit, `main` is fast-forwarded to the same commit, main-branch CI succeeds, and tagged-source smoke passes. Any source or documentation change before tagging creates a new candidate and invalidates older candidate-bound evidence.
