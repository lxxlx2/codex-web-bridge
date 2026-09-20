# Test suite guide

The test tree is intentionally kept flat for the first RC so existing imports,
CI commands, and release tooling remain stable. This file provides the logical
structure that a maintainer should use when deciding what to run.

Physical moves into `tests/unit`, `tests/integration`, or
`tests/acceptance` are deferred until after the release unless a correctness
change requires them.

## Test classes

### 1. Protocol and normalization

Primary files:

```text
test_codex_runtime_extraction.py
test_codex_responses_v2_contract.py
test_codex_responses_state.py
test_codex_responses_minimal_stream.py
test_codex_compat.py
```

Purpose:

- Responses input/output normalization;
- function-call/tool-result conversion;
- state persistence;
- compatibility boundaries.

### 2. Client-tool safety and repair

Primary files:

```text
test_client_tool_policy.py
test_client_tool_policy_context_path_refusal.py
test_client_tool_policy_post_tool_mount.py
test_client_tool_policy_repeated_refusal.py
test_client_tool_policy_root_workdir.py
test_codex_required_tool_continuation_patch.py
test_codex_required_tool_language_patch.py
test_codex_required_tool_phrasing.py
test_codex_uncertain_tool_effect_retry.py
test_codex_tool_xml_cdata.py
```

Purpose:

- real client tool requirements;
- tool-unavailable contradiction repair;
- provenance after compaction;
- unsafe workdir protection;
- uncertain side-effect handling;
- tool transport formatting.

A test that uses fake/user-shaped Function Call Output must state whether that
text is trusted bridge provenance or ordinary untrusted text.

### 3. Continuation, affinity, and compaction

Primary files:

```text
test_codex_web_session_affinity.py
test_codex_continuation_identity_fencing.py
test_codex_lost_affinity_restart_fallback.py
test_codex_v2_runtime_hardening.py
test_codex_remote_compaction_v2.py
test_codex_remote_compaction_compat.py
test_codex_remote_compaction_trigger_probe.py
test_codex_auto_compact_trigger_probe.py
test_codex_large_context_acceptance.py
test_codex_large_context_live.py
```

Purpose:

- same-thread continuity;
- response/call identity;
- restart recovery;
- compaction lineage;
- recursive compaction;
- post-compaction recovery.

### 4. Browser surface and lifecycle

Primary files:

```text
test_chatgpt_web_surface.py
test_chatgpt_web_surface_post_switch.py
test_chatgpt_web_surface_preflight.py
test_chatgpt_web_prepare.py
test_chatgpt_web_mode.py
test_chatgpt_web_rate_limit_guard.py
test_chatgpt_web_rate_limit_workflow_terminal.py
test_chatgpt_owned_unsent_composer_cleanup.py
test_stream_monitor_terminal_state.py
```

Purpose:

- safe Chat surface selection;
- composer state;
- rate-limit classification;
- generation terminal state;
- pre-send behavior;
- cleanup.

### 5. Lifecycle, route, and installation

Primary files:

```text
test_codex_provider_switch.py
test_codex_uwa_lifecycle.py
test_codex_route_audit.py
test_install_codex_uwa_commands.py
test_standalone_health.py
test_standalone_entrypoint.py
test_standalone_api_import_boundary.py
```

Purpose:

- wrapper behavior;
- listener ownership;
- route evidence;
- standalone import/API surface;
- health semantics.

### 6. Release and acceptance orchestration

Primary files:

```text
test_codex_desktop_acceptance_harness.py
test_codex_standalone_s3_runner.py
test_standalone_office_soak.py
test_standalone_release_confidence.py
test_standalone_desktop_e2e_gate.py
test_standalone_install_smoke.py
test_standalone_s4_release_gate.py
test_standalone_tagged_source_smoke.py
test_security_hardening.py
```

These tests validate the gate logic itself. They do not substitute for the real
live gates.

## Naming expectations

A useful test name should answer:

```text
given what state?
when what event happens?
what invariant must hold?
```

Prefer names such as:

```text
test_declared_workspace_tool_absence_claim_is_repaired_without_surviving_history
test_final_settle_generation_reappearance_resets_stability_window
test_failed_live_turn_stops_without_replaying_later_scenarios
```

Avoid names such as:

```text
test_bug
test_fix
test_case_2
```

When a regression comes from a live failure, include the semantic behavior in the
name instead of a private thread ID, timestamp, or operator-specific path.

## Assertions for side effects

Do not accept model prose as proof of side effects.

Where possible assert:

- exact file bytes;
- exact changed-path scope;
- command exit status;
- test pass/fail transition;
- request-manager terminal state;
- route evidence;
- candidate SHA.

The acceptance harness in `tools/codex_desktop_acceptance.py` intentionally
checks filesystem/Git state after model actions.

## Focused test workflow

Examples:

```bash
# tool policy / provenance
.venv/bin/python -m pytest -q tests/test_client_tool_policy*.py

# continuation / affinity
.venv/bin/python -m pytest -q   tests/test_codex_web_session_affinity.py   tests/test_codex_v2_runtime_hardening.py   tests/test_codex_required_tool_continuation_patch.py

# browser lifecycle
.venv/bin/python -m pytest -q   tests/test_stream_monitor_terminal_state.py   tests/test_chatgpt_web_*.py

# release confidence
.venv/bin/python -m pytest -q   tests/test_standalone_office_soak.py   tests/test_standalone_release_confidence.py   tests/test_standalone_s4_release_gate.py
```

Always finish a source change with:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python tools/public_repo_safety_check.py
.venv/bin/python tools/standalone_dependency_audit.py --check
```

## Live tests

Real ChatGPT Web acceptance is deliberately outside normal pytest/CI.

Live gate code is unit-tested here, but the actual live evidence is generated
through scripts in `tools/`.

See:

- [../docs/TESTING.md](../docs/TESTING.md)
- [../docs/RELIABILITY_MODEL.md](../docs/RELIABILITY_MODEL.md)
- [../tools/README.md](../tools/README.md)
