# Manifests

This directory contains extraction/provenance evidence from the standalone split. These files are not a live inventory of the current repository.

- `s1-audit-summary.json`: S1 source-baseline audit summary used to plan the conservative extraction.
- `bootstrap-candidate.json`: conservative S2 input manifest copied from the integration tree before later pruning and standalone-specific additions.

The pinned source baseline is recorded in the repository-root `SOURCE_BASELINE`.

Do not update `bootstrap-candidate.json` merely because the current tree gains or loses files. It is historical provenance evidence. Current runtime closure is evaluated by `tools/standalone_dependency_audit.py`, and current release contents are the exact Git commit/tag being validated.
