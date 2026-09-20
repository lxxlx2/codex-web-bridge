# Standalone S2 generic API prune checkpoint

> Historical engineering evidence. This file preserves the state and reasoning from its recorded stage; current release status is determined by exact-candidate gates. See [docs/README.md](README.md) for the current documentation map.\n\n
Date: 2026-09-10
Branch: `standalone-dev`

## Result

The standalone API and service package boundaries were tightened and the first generic API pruning tranche is complete.

The lazy compatibility export in `app.api` kept the integrated UWA aggregate router reachable in the static dependency graph even though standalone startup did not execute it. The package now has no aggregate router export, and `app.api.standalone_routes` imports the Codex runtime submodule directly.

After that seam was removed, the dependency audit identified ten generic API modules as both statically unreachable from the standalone seeds and absent from standalone startup. They were removed:

- `app.api.anthropic_routes`
- `app.api.browser_routes`
- `app.api.cmd_routes`
- `app.api.config_compare_support`
- `app.api.config_route_models`
- `app.api.config_routes`
- `app.api.config_workflow_support`
- `app.api.provider`
- `app.api.routes`
- `app.api.system`

A second package boundary was then tightened in `app.services`. Its package initializer had eagerly imported the legacy request/configuration service exports whenever any focused Codex service was imported. The standalone package initializer is now side-effect free.

## Validation

Standalone CI run `182` after the ten-module API prune completed successfully for all three jobs:

- `scaffold`: success
- `runtime-import`: success
- `codex-regression`: success

The audit after the API prune reported:

- runtime Python modules: 151
- static closure: 141
- startup-loaded local modules: 128
- static unreachable modules: 10
- prune candidates: 5
- obvious generic candidates: 0
- startup forbidden modules: none
- startup non-ChatGPT parsers: none

After making `app.services` side-effect free, the focused standalone import/regression/audit job remained green and startup-loaded local modules dropped from 128 to 119. The legacy `CFG_ENG` configuration-engine initialization message disappeared from standalone startup.

The remaining static path to the legacy configuration engine is now explicit and does not execute during startup:

`app.api.codex_runtime -> app.api.chat -> app.api.legacy_chat_runtime -> app.services.config_engine`

The remaining static path to the generic command engine is:

`app.api.codex_responses_v2 -> app.services.codex_web_session_affinity -> app.core.tab_pool -> app.core.tab_pool_parts.manager -> app.services.command_engine`

These are the next S2 extraction seams. They should be removed by replacing the remaining compatibility dependencies with standalone-focused implementations, followed by the same full CI and dependency-audit gates.

## Protected candidates

`security_guard.py` can appear as unreachable from the runtime import closure because it is a release/public-safety tool rather than an application runtime dependency. It remains intentionally retained.
