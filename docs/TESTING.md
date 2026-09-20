# Testing guide

## Testing philosophy

Codex Web Bridge is tested in layers because deterministic Python behavior and
live ChatGPT Web behavior have different failure modes.

The release-critical rule is:

```text
all candidate-bound evidence must identify the exact same Git commit
```

A passing unit test does not replace live evidence. A historical live PASS does
not transfer to a new commit. A Web rate-limit failure does not automatically
invalidate the candidate source, but it also does not count as a successful
release run.

See [RELIABILITY_MODEL.md](RELIABILITY_MODEL.md) for the confidence model and
[../tests/README.md](../tests/README.md) for test ownership.

## Everyday developer loop

Start narrow:

```bash
.venv/bin/python -m pytest -q <focused tests>
```

Then run the deterministic release baseline:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python tools/public_repo_safety_check.py
.venv/bin/python tools/standalone_dependency_audit.py --check
```

Do not use a successful live run as a reason to skip deterministic regressions.

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
| acceptance workspace effects | `tests/test_codex_desktop_acceptance_harness.py` |
| office-work soak orchestration | `tests/test_standalone_office_soak.py` |
| repeated-live confidence | `tests/test_standalone_release_confidence.py` |
| install wrappers | `tests/test_install_codex_uwa_commands.py`, `tests/test_standalone_install_smoke.py` |
| security/repository hygiene | `tests/test_security_hardening.py`, public safety scanner |
| S3 runner | `tests/test_codex_standalone_s3_runner.py` |
| Desktop gate | `tests/test_standalone_desktop_e2e_gate.py` |
| S4 gate | `tests/test_standalone_s4_release_gate.py` |
| tagged source | `tests/test_standalone_tagged_source_smoke.py` |

Always run the full suite after focused tests when source code changes.

## Deterministic CI

`.github/workflows/standalone-ci.yml` is the repository gate. It covers:

- static/compile checks;
- standalone import and route boundaries;
- focused runtime regressions;
- broad Codex regressions;
- public-repository safety;
- dependency closure;
- release metadata and gate unit tests.

GitHub CI does not log into ChatGPT Web.

A cancelled duplicate run caused by workflow concurrency is not a functional
failure when the exact same SHA has another completed successful run.

## Live gate precondition

Before any expensive live gate:

```text
candidate source frozen for that attempt
worktree clean
exact local HEAD recorded
browser/CDP healthy
ChatGPT Web surface ready
composer empty
no rate-limit/quota/auth/challenge blocker
request manager clean
```

Live gates must stop if these conditions cannot be proven.

The first RC intentionally has no automatic fallback provider. A failed Web path
produces a clear failure instead of silently switching to a local model or API.

## Clean-checkout install / rollback smoke

Run:

```bash
.venv/bin/python tools/standalone_install_smoke.py
```

This verifies:

- dependency bootstrap;
- installed lifecycle wrappers;
- wrapper root ownership;
- standalone listener ownership;
- basic real Codex request;
- `codex-official` rollback;
- switch-back behavior;
- authentication preservation.

The smoke result must bind to the current candidate commit.

## S3 full live acceptance

Run:

```bash
.venv/bin/python tools/standalone_s3_live_acceptance.py
```

One S3 PASS proves in one unattended run:

- repository preflight;
- safe ChatGPT Web surface preflight;
- real client-tool round trip;
- same-thread restart recovery;
- native auto-compaction;
- Remote V2 compaction;
- post-compaction recovery;
- `uwa / chatgpt / high` route evidence;
- request-manager cleanup;
- repository cleanliness.

Required terminal marker:

```text
STANDALONE_S3=PASS_LIVE_CLOSED
```

### Repeated S3 release requirement

For v0.1.0-rc.1, one S3 PASS is not enough to publish.

The exact candidate must accumulate:

```text
>= 3 S3 PASS_LIVE_CLOSED results
>= 2 distinct two-hour UTC evidence windows
```

The positive evidence is checked later by
`tools/standalone_release_confidence.py`.

Do not immediately rerun a failed S3 without classifying it.

## External live failures

Examples:

- ChatGPT Web rate limit;
- usage/quota exhausted;
- auth interruption;
- challenge/interstitial;
- temporary Web availability issue.

Required behavior:

```text
run stops
failure class is explicit
no alternate provider is selected
uncertain side-effecting tool is not replayed
request manager reaches terminal cleanup
```

When the failure is external and the source did not change, wait for the external
condition to clear and start a later live attempt. That attempt is new evidence.

External failures do not count toward the three required S3 successes.

## Office-work soak

Run:

```bash
.venv/bin/python tools/standalone_office_soak.py
```

The office soak complements S3 with safe, reversible work patterns inside the
isolated acceptance workspace.

It covers:

- same-thread context recall;
- byte-exact result-file verification;
- multi-file implementation edits;
- independent test execution;
- failure -> fix -> rerun workflow;
- requirements-driven config edits;
- Git diff scope;
- long-running process plus stdin continuation;
- route and cleanup.

Required markers:

```text
STANDALONE_OFFICE_SOAK=PASS
OFFICE_SOAK_EFFECT_VERIFICATION=PASS
```

The key principle is effect verification: model prose is not accepted as proof
that a file was written, an edit was scoped correctly, or a test actually
passed.

## Release confidence aggregation

After the required successful S3 runs and the office soak exist for the same
candidate:

```bash
.venv/bin/python tools/standalone_release_confidence.py
```

Required terminal result:

```text
STANDALONE_RELEASE_CONFIDENCE=PASS
```

The aggregator reads private result markers only. It does not contact ChatGPT
Web or rerun any side effect.

## Codex Desktop E2E

Prepare:

```bash
.venv/bin/python tools/standalone_desktop_e2e_gate.py prepare
```

Perform the printed Desktop prompts, then:

```bash
.venv/bin/python tools/standalone_desktop_e2e_gate.py verify
```

Required result:

```text
STANDALONE_DESKTOP_E2E=PASS
```

This complements CLI-driven S3/soak evidence with the real Desktop application.

## S4 exact-candidate consistency

Run:

```bash
.venv/bin/python tools/standalone_s4_release_gate.py
```

S4 binds all release-control evidence to the current HEAD and verifies:

- docs/version/security/provenance;
- release confidence;
- install smoke;
- S3 candidate identity;
- Desktop E2E candidate identity.

Required result:

```text
STANDALONE_S4_LOCAL=PASS
```

## Tagged-source smoke

After `main` points to the exact validated candidate, main CI is green, and the
tag exists, use a fresh checkout of the tag:

```bash
.venv/bin/python tools/standalone_tagged_source_smoke.py
```

Required result:

```text
TAGGED_SOURCE_SMOKE=PASS
```

## Release order

The release sequence is:

```text
focused tests
-> full suite
-> public safety + dependency audit
-> exact-SHA CI
-> clean install/rollback smoke
-> S3 success #1
-> S3 success #2/#3 across >= 2 evidence windows
-> office-work soak
-> release confidence aggregator
-> Codex Desktop E2E
-> S4 exact-candidate consistency
-> fast-forward main to exact candidate
-> main CI
-> tag
-> tagged-source smoke
-> GitHub Release
```

The order of the three successful S3 runs and office soak may be interleaved to
respect account availability, but every positive result must bind to the same
candidate SHA.

## Candidate invalidation

Any source or release-document change before tagging creates a new candidate.

Regenerate candidate-bound evidence after changes to:

- runtime code;
- tests that define release behavior;
- release/acceptance tooling;
- release requirements/design/test plan;
- public release documentation used by S4.

An external Web failure without a source change does not create a new candidate.

## What not to do

Do not:

- weaken a gate to make an observed failure disappear;
- count a rate-limited run as a PASS;
- replay an uncertain side-effecting tool automatically;
- copy raw private live traces into the repository;
- use a historical PASS from another SHA;
- silently substitute another inference backend.

See [RELEASE_TEST_PLAN.md](RELEASE_TEST_PLAN.md) for the formal release matrix.
