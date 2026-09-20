# Roadmap

This roadmap separates first-release stabilization from later structural cleanup.

## v0.1.0-rc.1

Before the first RC tag:

- keep the runtime/test/tool path layout stable, but add durable project, maintainer, test, and tooling maps so handoff does not depend on tribal knowledge;
- publish the project overview, reliability model, architecture, development, testing, troubleshooting, and maintainer-handoff docs;
- remove machine-specific conversation/session identifiers from tracked configuration;
- strengthen public-repository safety checks;
- independently verify acceptance side effects instead of trusting model completion prose;
- require at least three full S3 live passes on the exact candidate across at least two two-hour UTC evidence windows;
- require an office-work soak on the same candidate;
- aggregate repeated-live evidence with the release-confidence gate before S4;
- keep rc.1 on one ChatGPT Web inference path and fail explicitly rather than adding an automatic provider/local-model/API fallback;
- regenerate the complete candidate-bound release matrix after the final release-tree commit;
- fast-forward `main`, run main CI, create the RC tag, perform tagged-source smoke, then create the GitHub Release.

## RC observation period

After `v0.1.0-rc.1` is published:

- verify installation from the tag on a clean checkout;
- collect real-world compatibility reports without changing the RC tag;
- classify ChatGPT Web UI changes separately from bridge regressions;
- fix only release-blocking or high-confidence compatibility defects;
- use `v0.1.0-rc.2` if the RC source must change before stable.

## v0.1.0 stable

Promote to stable when the RC has no unresolved release blocker and the stable candidate passes the release matrix.

If no source changes are needed, stable may use the same source tree with a stable version/tag update and the corresponding version/docs gates. If source changes are needed, create a new candidate and regenerate exact-SHA evidence.

Stable-release documentation should state the verified platform scope and clearly mark Windows/Linux live certification status.

## Post-v0.1.0 engineering

The first stable release intentionally prioritizes conservative compatibility over aggressive cleanup. After stable:

1. Runtime slimming
   - re-run static/runtime closure analysis;
   - remove retained provider/media/config code that can be proven unreachable;
   - reduce `config/sites.json` to the minimum standalone runtime surface when safe.

2. Package/dependency reproducibility
   - add standard Python project metadata if packaging becomes useful;
   - add a validated release constraints/lock strategy;
   - keep supported ranges separate from exact release-tested versions.

3. Cross-platform certification
   - add equivalent Windows and Linux live acceptance;
   - document platform-specific browser/CDP and wrapper behavior.

4. Repository structure cleanup
   - consider `tests/unit`, `tests/integration`, `tests/acceptance`;
   - consider `tools/dev`, `tools/acceptance`, `tools/release`;
   - only move paths with import/CI/install compatibility coverage.

5. Large-module decomposition
   - split oversized inherited modules only after behavior is frozen by characterization tests;
   - prioritize `request_manager.py`, browser workflow, stream monitoring, tab pool, and command-engine seams.

6. Developer automation
   - optional task runner for common focused/full/safety checks;
   - generated release evidence summary from private candidate results without publishing private traces.

7. Observability and compatibility
   - keep sanitized failure classes stable;
   - improve Web-surface diagnostics without exposing private session content;
   - track ChatGPT Web DOM/behavior changes with focused regression fixtures.

## Non-goals

The roadmap does not include bypassing account limits, automating account rotation to evade throttling, or granting ChatGPT Web direct local filesystem/shell authority.
