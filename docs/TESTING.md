# Testing guide

## Principles

Tests are layered. A passing unit test does not replace live evidence, and a historical live PASS does not replace deterministic regression on the current commit.

The release-critical rule is:

```text
all candidate-bound evidence must identify the exact same commit
```

## Everyday developer loop

Run a focused test first, then the full suite:

```bash
.venv/bin/python -m pytest -q <focused tests>
.venv/bin/python -m pytest -q
```

Repository safety:

```bash
.venv/bin/python tools/public_repo_safety_check.py
.venv/bin/python tools/standalone_dependency_audit.py
```

## Change-to-test map

| Area changed | Start with |
| --- | --- |
| stream terminal state / generation selectors | `tests/test_stream_monitor_terminal_state.py` |
| ChatGPT Web surface/readiness | `tests/test_chatgpt_web_surface*.py`, `tests/test_chatgpt_web_prepare.py` |
| rate-limit handling | `tests/test_chatgpt_web_rate_limit*.py` |
| client-tool policy/refusal recovery | `tests/test_client_tool_policy*.py`, `tests/test_codex_workspace_refusal_language_patch.py` |
| Responses normalization | `tests/test_codex_runtime_extraction.py`, `tests/test_codex_responses_v2_contract.py` |
| conversation affinity | `tests/test_codex_web_session_affinity.py` |
| required-tool continuation | `tests/test_codex_required_tool_*.py` |
| Remote V2 compaction | `tests/test_codex_remote_compaction*.py` |
| provider/lifecycle wrappers | `tests/test_codex_provider_switch.py`, `tests/test_codex_uwa_lifecycle.py` |
| install wrappers | `tests/test_install_codex_uwa_commands.py`, `tests/test_standalone_install_smoke.py` |
| security/repository hygiene | `tests/test_security_hardening.py`, public safety scanner |
| S3 runner | `tests/test_codex_standalone_s3_runner.py` |
| Desktop gate | `tests/test_standalone_desktop_e2e_gate.py` |
| S4 gate | `tests/test_standalone_s4_release_gate.py` |

Always run the full suite after focused tests.

## CI

`.github/workflows/standalone-ci.yml` is the deterministic repository gate. It covers static/scaffold checks, runtime import boundaries, focused Codex regressions, security/provenance checks, and the broad test suite.

A cancelled duplicate run caused by workflow concurrency is not a functional failure when the exact same SHA has another completed successful run.

## Live release gates

### S3

```bash
.venv/bin/python tools/standalone_s3_live_acceptance.py
```

S3 proves in one unattended run:

- repository preflight;
- real client-tool round trip;
- same-thread restart recovery;
- native auto-compaction;
- Remote V2 compaction;
- post-compaction recovery;
- `uwa / chatgpt / high` route;
- request-manager cleanup;
- repository cleanliness.

Release closure requires:

```text
STANDALONE_S3=PASS_LIVE_CLOSED
```

Do not repeatedly rerun a live failure without classifying it. External ChatGPT rate limiting is recorded as an external failure and must not be “fixed” by weakening correctness conditions.

### Codex Desktop E2E

Prepare:

```bash
.venv/bin/python tools/standalone_desktop_e2e_gate.py prepare
```

Perform the printed Desktop prompts exactly as documented in [DESKTOP_E2E_GATE.md](DESKTOP_E2E_GATE.md), then verify:

```bash
.venv/bin/python tools/standalone_desktop_e2e_gate.py verify
```

Required terminal result:

```text
STANDALONE_DESKTOP_E2E=PASS
```

### Clean-checkout install smoke

```bash
.venv/bin/python tools/standalone_install_smoke.py
```

This verifies dependency bootstrap, target reset, wrappers, real basic Codex request, official rollback, listener ownership, and authentication preservation from an isolated checkout/home.

### S4 exact-candidate consistency

```bash
.venv/bin/python tools/standalone_s4_release_gate.py
```

S4 verifies docs/version/security/provenance plus install, S3, and Desktop evidence binding to the current Git HEAD.

Required result:

```text
STANDALONE_S4_LOCAL=PASS
```

## Release order

The release sequence is:

```text
focused/static
-> full suite
-> exact-SHA CI
-> S3 live
-> Desktop E2E
-> install smoke
-> S4
-> fast-forward main to the exact candidate
-> main CI
-> tag
-> tagged-source smoke
-> GitHub Release
```

If any source or documentation file changes before the tag, treat the new commit as a new candidate and regenerate the candidate-bound gates required by the release policy.

After creating the tag, use a fresh checkout of that tag and run:

```bash
.venv/bin/python tools/standalone_tagged_source_smoke.py
```

Required result:

```text
TAGGED_SOURCE_SMOKE=PASS
```

The release smoke checks tag identity, version, required public files, repository cleanliness, public-repository safety, and dependency closure.

See [RELEASE_TEST_PLAN.md](RELEASE_TEST_PLAN.md) for the full formal matrix.
