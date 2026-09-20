# Changelog

All notable standalone release changes will be documented here.

## 0.1.0-rc.1

Release-candidate scope for Codex Web Bridge:

- Closed S1 dependency/import/runtime audit and S2 standalone extraction/decoupling.
- Added standalone lifecycle/provider wrappers, loopback-safe defaults, public-repository safety checks, dependency/provenance gates, and clean-checkout install smoke.
- Added ChatGPT Web surface classification, Chat/Work normalization for acceptance, quota/rate-limit fail-closed behavior, and bounded request cleanup.
- Added Codex Responses V2 continuity, real client-tool round trips, restart continuity, native/Remote V2 compaction, required-tool hardening, and private wire observability.
- Added a release-blocking real Codex Desktop E2E gate covering same-thread context, real local tool execution, route verification, and request-manager cleanup.
- Added full standalone test collection enforcement and removed orphaned legacy tests whose implementation scripts were intentionally excluded from the standalone tree.
- Added contributor onboarding: architecture, development, testing, troubleshooting, documentation index, roadmap, and pull-request guidance.
- Removed machine-specific remembered browser conversation/route state from tracked defaults and extended public-repository safety checks to reject raw AI conversation URLs.
- Strengthened S4 documentation consistency checks so stale release-state snapshots cannot silently pass the final local gate.
- Added a dedicated tagged-source smoke runner and durable known-limitations/roadmap documentation for the RC-to-stable path.
- Hardened post-compaction large-context recovery to require byte-exact trailing-newline verification and added precise result-mismatch classification.
- Hardened stream terminal completion against a final-settle generation reappearance race and added composer-scoped Stop-state detection plus diagnostic source logging.
- Repaired recursive-compaction tool-availability contradictions directly from the current declared client-tool schema, even when immediate function-call provenance has been compacted away.
- Added release-hardening documentation for the project core goal, single-backend fail-closed policy, maintainer handoff, test ownership, tooling ownership, and release reliability model.
- Added an office-work live soak covering context continuity, multi-file edits, real failure recovery, Git diff discipline, and interactive processes with independent effect verification.
- Added a release-confidence aggregator that requires at least three successful full S3 runs on the exact candidate across at least two two-hour UTC evidence windows, plus a candidate-bound office-work soak.
- Strengthened S4 so repeated-live release confidence is required before the final local release gate can pass.
- Strengthened the synthetic Desktop acceptance checker so the multi-file scenario verifies the expected changed-file scope instead of trusting only the test result.
- Release evidence is exact-candidate-bound: deterministic regression, exact-SHA CI, clean-install smoke, repeated S3 live passes, office-work soak, release-confidence aggregation, Desktop E2E, S4, main CI, and tagged-source smoke are required before the GitHub Release.

## Unreleased

Post-RC work remains intentionally out of scope for the first candidate, including broader runtime slimming, cross-platform live certification, and non-release feature work.
