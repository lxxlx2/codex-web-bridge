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

Do not create a GitHub Release from a temporary hardening or development branch. A tag is publishable only after all of the following are true:

1. S1 dependency/import/runtime audit is closed.
2. S2 standalone extraction and decoupling is closed.
3. Deterministic focused/full regression, public-repository safety, dependency audit, and exact-SHA CI are green.
4. Clean-checkout install / official rollback smoke passes on the exact candidate.
5. The exact candidate has at least three full `STANDALONE_S3=PASS_LIVE_CLOSED` results spanning at least two two-hour UTC evidence windows.
6. The exact candidate passes the office-work soak with independent effect verification.
7. `tools/standalone_release_confidence.py` passes and binds repeated S3 + soak evidence to the current candidate.
8. Codex Desktop E2E passes on the same candidate.
9. S4 docs/version/security/provenance/evidence consistency passes on the same candidate.
10. The release tree is clean and `main` is fast-forwarded to the exact validated candidate commit.
11. The main-branch CI run for that exact commit is green.
12. `VERSION`, `CHANGELOG.md`, README status and release notes agree with the tag.
13. A fresh checkout of the tag passes the documented tagged-source smoke before the GitHub Release is published.

External ChatGPT Web rate limits, quota/auth/challenge blockers, or temporary availability failures stop the current live run. They do not count as positive evidence and do not trigger an automatic fallback to another inference backend.

## Planned release contents

Each Release should identify the exact commit and verified environment, summarize user-visible changes and known limitations, and publish integrity metadata for any generated archive or installer. GitHub automatically provides source-code ZIP and tar.gz snapshots for the tagged commit.

The project may later add generated convenience bundles and SHA-256 checksums, but those artifacts must be produced from the tagged `main` commit and must not contain browser profiles, cookies, credentials, private Responses state, prompts, tool bodies, wire traces or other local state.

After creating the RC tag, clone/check out that tag in a fresh directory, create its project environment, and run:

```bash
.venv/bin/python tools/standalone_tagged_source_smoke.py
```

Do not publish the GitHub Release unless it ends with `TAGGED_SOURCE_SMOKE=PASS`.

## Current state

`standalone-dev` is the canonical development/candidate branch and `main` is the release boundary. Temporary hardening branches may be used for coordinated pre-release work, but live release evidence is generated only after the final tree is merged back into the canonical candidate branch.

A release commit is publishable only when deterministic CI, repeated S3 live evidence, office-work soak, release-confidence aggregation, Desktop E2E, clean-install smoke, and S4 all bind to that exact commit; `main` is then fast-forwarded to the same commit, main-branch CI succeeds, and tagged-source smoke passes.

Any source or release-document change before tagging creates a new candidate and invalidates older candidate-bound evidence that no longer matches its SHA.
