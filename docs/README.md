# Documentation index

This directory separates durable contributor guidance from release-specific design and historical acceptance evidence.

## Start here

- [Architecture](ARCHITECTURE.md): request flow, trust boundaries, state, module ownership, and compatibility facades.
- [Development](DEVELOPMENT.md): local environment, lifecycle commands, configuration policy, and safe change workflow.
- [Testing](TESTING.md): focused test map, CI layers, live gates, and exact-candidate rules.
- [Troubleshooting](TROUBLESHOOTING.md): common failure signatures, root causes, and the regression tests that protect them.
- [Roadmap](ROADMAP.md): post-RC stabilization and the planned structural cleanup after the first stable release.
- [Contributing](../CONTRIBUTING.md): pull-request workflow and repository hygiene.

## Release specification

These files define the v0.1.0-rc.1 release contract:

- [RELEASE_REQUIREMENTS.md](RELEASE_REQUIREMENTS.md)
- [RELEASE_TECHNICAL_DESIGN.md](RELEASE_TECHNICAL_DESIGN.md)
- [RELEASE_TEST_PLAN.md](RELEASE_TEST_PLAN.md)
- [RELEASE_PROCESS.md](RELEASE_PROCESS.md)
- [RELEASE_PLAN.md](RELEASE_PLAN.md)

Treat those documents as release policy and design records. Candidate-bound evidence is valid only for the exact commit on which it was produced.

## Historical engineering evidence

The following files are detailed implementation/acceptance records. They are intentionally retained because they explain why apparently defensive lifecycle, tool-policy, compaction, and browser-state code exists:

- [S1_AUDIT_FINDINGS.md](S1_AUDIT_FINDINGS.md)
- [STANDALONE_S2_BROAD_REGRESSION_2026-09-10.md](STANDALONE_S2_BROAD_REGRESSION_2026-09-10.md)
- [STANDALONE_S2_CHATGPT_EXECUTOR_2026-09-10.md](STANDALONE_S2_CHATGPT_EXECUTOR_2026-09-10.md)
- [STANDALONE_S2_CLOSURE_2026-09-10.md](STANDALONE_S2_CLOSURE_2026-09-10.md)
- [STANDALONE_S2_GENERIC_API_PRUNE_2026-09-10.md](STANDALONE_S2_GENERIC_API_PRUNE_2026-09-10.md)
- [STANDALONE_S2_RUNTIME_SEAM_2026-09-10.md](STANDALONE_S2_RUNTIME_SEAM_2026-09-10.md)
- [STANDALONE_S3_LIVE_GATE_2026-09-10.md](STANDALONE_S3_LIVE_GATE_2026-09-10.md)
- [STANDALONE_S4_INSTALL_SMOKE_2026-09-17.md](STANDALONE_S4_INSTALL_SMOKE_2026-09-17.md)
- [DESKTOP_E2E_GATE.md](DESKTOP_E2E_GATE.md)

For day-to-day development, use the durable guides above instead of reading the historical files linearly.
