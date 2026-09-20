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
- Release evidence is exact-candidate-bound: final S3 live closure, Desktop E2E, clean-install smoke, CI, S4, main CI, and tagged-source smoke are required in the documented order before the GitHub Release.

## Unreleased

Post-RC work remains intentionally out of scope for the first candidate, including broader runtime slimming, cross-platform live certification, and non-release feature work.
