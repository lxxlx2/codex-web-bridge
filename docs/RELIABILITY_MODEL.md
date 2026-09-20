# Reliability model

## Why release confidence needs more than one PASS

Codex Web Bridge sits between deterministic local software and a nondeterministic Web model/browser surface. The same release candidate can encounter different Web timing, output shape, compaction timing, account throttling, or model behavior across runs.

The project therefore separates three kinds of evidence:

1. deterministic repository evidence;
2. candidate-bound live protocol evidence;
3. office-like side-effect verification.

A release is allowed only when all required evidence points to the same Git commit.

## Layer 1: deterministic repository evidence

Required on every candidate:

```text
focused regressions
full pytest suite
public repository safety
dependency audit
exact-SHA GitHub CI
clean worktree
```

These checks must be reproducible. A deterministic test that fails is a product/test-contract issue and must be resolved before live acceptance.

## Layer 2: repeated S3 live evidence

One S3 PASS proves that the full chain worked once. It does not prove that browser timing, continuation, compaction, and Web lifecycle behavior are stable enough for release.

For v0.1.0-rc.1, release confidence requires:

```text
same exact candidate SHA
>= 3 full S3 PASS_LIVE_CLOSED results
>= 2 distinct two-hour UTC evidence windows
```

Each successful S3 must independently prove:

- safe Web surface preflight;
- real client tool execution;
- same-thread restart continuity;
- native auto-compaction;
- Remote V2 compaction;
- post-compaction recovery;
- `uwa / chatgpt / high` route evidence;
- request-manager cleanup;
- clean release repository.

The actual elapsed-span requirement prevents a pair of runs close to a UTC bucket boundary from looking more independent than they are.

The positive evidence gate is implemented by:

```bash
.venv/bin/python tools/standalone_release_confidence.py
```

## External failure semantics

The release gate distinguishes positive evidence from candidate invalidation.

Examples of external conditions:

- ChatGPT Web rate limit;
- account quota;
- authentication interruption;
- challenge/interstitial;
- temporary Web availability failure.

When one occurs:

```text
current run = FAIL
candidate source = not automatically invalidated
success counter = unchanged
automatic fallback = none
automatic replay of uncertain side effects = none
```

The operator waits for the external condition to clear and starts a new acceptance attempt later.

An external failure never counts as one of the required successful S3 runs.

## Layer 3: office-work soak

Synthetic compaction tests are necessary but not sufficient for everyday work confidence.

The release-blocking office soak runs safe tasks only in the isolated acceptance workspace and verifies their real postconditions independently of the model's final prose.

Coverage:

```text
context continuity
multi-file edit
tests after edit
failure -> diagnosis -> fix -> rerun
requirements-driven config edit
git-diff scope discipline
long-running command
write_stdin continuation
route verification
request cleanup
repository cleanliness
```

Run:

```bash
.venv/bin/python tools/standalone_office_soak.py
```

Required result:

```text
STANDALONE_OFFICE_SOAK=PASS
OFFICE_SOAK_EFFECT_VERIFICATION=PASS
```

The soak does not permit fallback to a different provider.

## Effect verification

A model saying “done” is not release evidence.

Acceptance checks verify observable state after the model action.

Examples:

```text
write file
-> read/check exact bytes or semantic contents

edit implementation
-> run tests
-> inspect changed-path scope

failure recovery
-> prove the first run failed
-> prove the final run passed

interactive process
-> verify exact result file

route
-> verify configuration/session/wire evidence
```

This principle should be used when adding future acceptance scenarios: verify the effect, not the wording of the final answer.

## What the release can and cannot claim

A passing release matrix supports claims about:

- protocol compatibility;
- local client-tool handoff;
- route correctness;
- continuation behavior;
- compaction behavior;
- lifecycle cleanup;
- fail-closed handling;
- tested safe side effects.

It does not prove that an AI model will choose the correct solution for every real business task.

Users should still apply normal Codex sandbox, approval, code review, test, and Git practices to consequential work.

## Release confidence gate

The private evidence layout is:

```text
~/.uwa/standalone-s3/<timestamp>/result.txt
~/.uwa/standalone-office-soak/<timestamp>/result.txt
~/.uwa/standalone-release-confidence/result.txt
```

The public repository never stores raw live prompts, command bodies, tool output, private thread identifiers, or full wire traces.

The aggregate result contains only sanitized markers and the candidate commit.

## Candidate invalidation

A candidate must be replaced when a source or release-document commit changes the release tree.

Product failures in any of these areas also invalidate the candidate until fixed:

- routing;
- client-tool protocol;
- continuation;
- compaction;
- browser lifecycle;
- request cleanup;
- installer/rollback;
- security/public-repository policy;
- release metadata.

External ChatGPT Web throttling alone does not change the source SHA and therefore does not require a source change.

## Release ordering

The reliability-sensitive release order is:

```text
deterministic local validation
-> exact-SHA CI
-> clean install/rollback smoke
-> repeated S3 live evidence
-> office-work soak
-> release confidence aggregator
-> Codex Desktop E2E
-> S4 exact-candidate consistency
-> fast-forward main
-> main CI
-> tag
-> tagged-source smoke
-> GitHub Release
```

Any release-tree change before tagging creates a new candidate and invalidates the candidate-bound evidence that no longer matches its SHA.
