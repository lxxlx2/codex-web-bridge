# Standalone S4 install smoke status — 2026-09-17

> Historical engineering evidence. This file preserves the state and reasoning from its recorded stage; current release status is determined by exact-candidate gates. See [docs/README.md](README.md) for the current documentation map.\n\n
## Historical gate snapshot

This file is retained as the engineering record for the S4 install-smoke false negative discovered on 2026-09-17. It is not the source of truth for the current release candidate.

The snapshot below refers to an older candidate:

- branch: `standalone-dev`
- candidate HEAD: `ffd89cfc5a9e36ea9e71ba52dddc166ea1785052`
- candidate commit: `Test trusted Chat mode click path`

Current release status is determined by the latest exact-candidate install-smoke result plus `tools/standalone_s4_release_gate.py`.

## Historical failing result

The clean-checkout install smoke failed at the ChatGPT surface preflight with:

```text
INSTALL_SMOKE=FAIL
FAILURE_CLASS=chatgpt_surface_unknown
FAILURE_DETAIL=send_missing
PRIVATE_EVIDENCE_RECORDED=YES
```

Private evidence from the local run confirmed:

```json
{
  "actions": [],
  "blocking_reason": "send_missing",
  "failure_class": "chatgpt_surface_unknown",
  "ok": false,
  "surface_kind": "chat",
  "target_count": 1
}
```

The target-reset evidence confirmed one stale target was closed and a fresh ChatGPT target was created successfully.

## Diagnosis

This failure is downstream of the recently hardened Work-to-Chat normalization path.

The preflight successfully classifies the fresh target as a Chat surface, but `app/services/chatgpt_web_surface.py` currently requires a visible send control even while the composer is empty. Current ChatGPT composer states may not expose the actual send control until text is inserted, which can produce a false-negative `send_missing` readiness result.

The S4 preflight should prove that the owned target is safe and ready for input. Actual submit capability is exercised immediately afterward by the real Codex request gate.

## Next change

Keep the change narrow and release-safe:

1. Update the ChatGPT surface readiness contract so an empty, verified Chat surface with a visible prompt can pass preflight without requiring a visible send control.
2. Continue collecting `send_control_present` as sanitized telemetry.
3. Preserve fail-closed behavior for Work surface, ambiguous target, dirty composer, auth/challenge, quota and rate-limit blockers.
4. Add focused regression coverage for an empty Chat composer whose send control is absent before input.
5. Run the focused surface/preflight/install-smoke tests, then rerun the full clean-checkout install smoke.
6. Commit and push code, tests and this progress update together before advancing the release gate.

## Reference-project check

Checked on 2026-09-17:

- `lumingya/universal-web-api`
- `leeguooooo/chatgpt-use`
- `kev489/gpt-tool-use`

No commits were published by these three repositories from 2026-09-15 through the check time, so there is no new upstream change that should interrupt S4.

Existing public reference behavior does support the narrow diagnosis: one reference waits for the ChatGPT composer itself before submission, while another locates and validates the send control during the actual submit phase after the prompt is populated. Treat these as interoperability ideas only; do not copy third-party source into this repository without explicit compatible-license review and attribution.

## Release discipline

Do not broaden this fix into a selector rewrite, mode-switch rewrite, or transport refactor. The immediate objective is to remove the confirmed preflight false negative, preserve existing safety guards, and continue the S4 smoke from the next gate.


## Implementation prepared

The confirmed `send_missing` false negative is addressed with a narrow
readiness-contract change.

- An empty, verified Chat surface no longer requires a currently visible send
  control in order to be safe for input.
- `send_control_present` remains available as sanitized telemetry.
- Dirty composer, Work surface, ambiguous target, authentication, challenge,
  quota and rate-limit guards remain unchanged.
- Actual submission capability remains covered by the real Codex request in the
  install smoke.
- A focused regression test covers the empty-composer/no-send-control state.

No broader Chat/Work selector, transport or browser-workflow refactor is included
in this S4 fix.
