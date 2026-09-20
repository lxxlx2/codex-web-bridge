## Summary

Describe the problem and the change.

## Root cause / design rationale

Explain the owning layer and the invariant being changed.

## Tests

- [ ] Focused regression(s)
- [ ] Full `pytest` suite
- [ ] `tools/public_repo_safety_check.py`
- [ ] `tools/standalone_dependency_audit.py` when dependency/runtime closure may change

Commands/results:

```text
paste sanitized results here
```

## Release impact

- [ ] No candidate-bound live invariant changed
- [ ] S3 must be regenerated
- [ ] Desktop E2E must be regenerated
- [ ] Install smoke must be regenerated
- [ ] S4 must be regenerated

## Security / privacy

Confirm that the change does not add credentials, cookies, private prompts, command/tool bodies, raw conversation/session identifiers, browser profiles, or private runtime traces.

## Documentation

List any user/developer/release documentation updated with the change.
