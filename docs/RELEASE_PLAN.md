# Standalone release plan

The validated integrated Codex Web Bridge V2 implementation already passed M1-M7 in `lxxlx2/universal-web-api`.

This repository follows a separate standalone release path:

```text
S1 dependency/import/runtime audit
S2 extraction, decoupling and minimal runtime
S3 CI + CLI/Desktop/live parity acceptance
S4 release candidate and first public release
```

## S1 exit criteria

S1 closes only when the source baseline is pinned and the following sets are identified with evidence: bridge core, required upstream runtime, release-validation code, non-Python runtime assets, external dependencies, exclusion candidates and license/provenance obligations.

## S2 exit criteria

The standalone development tree must remove generic Universal Web API surfaces that are not required by Codex Web Bridge. Import-time package side effects and broad router/parser registration must be narrowed where they pull unrelated providers into the runtime.

The result must have a standalone entrypoint, explicit dependency file, private-state defaults, English and Chinese documentation, AGPL-3.0 license continuity, attribution and public-repository safety checks.

## S3 exit criteria

The standalone tree must pass CI and local parity checks covering Responses compatibility, real client-tool calls, continuation, restart recovery, remote/native compaction, stream cancellation cleanup, route verification and request-manager cleanup. At least one real Codex Desktop/CLI live run must verify the standalone repository rather than the integration tree.

## S4 exit criteria

Only after S3 and the remaining candidate-bound release matrix pass may the standalone development branch be fast-forwarded to `main` and tagged. The first candidate tag should be `v0.1.0-rc.1`. Before the GitHub Release, main CI and tagged-source smoke must also pass. A stable `v0.1.0` follows the RC observation period once no release blocker remains and the stable candidate passes the required matrix.

Release notes should include the validated platform/Python/Codex ranges, known limitations, upgrade/install instructions, source baseline, upstream attribution and checksums for any attached binary/archive artifacts.


## Post-release work

The first RC intentionally avoids broad runtime refactoring. After release, follow [ROADMAP.md](ROADMAP.md) for RC observation, stable promotion, cross-platform certification, dependency reproducibility, runtime slimming, and later directory/module restructuring.
