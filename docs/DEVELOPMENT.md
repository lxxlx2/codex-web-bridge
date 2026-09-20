# Development guide

## Environment

The dependency floor is Python 3.10. The first RC release path is live-certified primarily on macOS; Windows and Linux are not release-blocking unless equivalent live evidence is explicitly added.

Create an isolated environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements-dev.txt
```

Install lifecycle wrappers:

```bash
.venv/bin/python tools/install_codex_uwa_commands.py
export PATH="$HOME/bin:$PATH"
```

The bridge expects a Chromium-compatible browser reachable through the configured CDP endpoint. The default browser port is `9222`. The controlled browser must have a usable logged-in ChatGPT Web session for live requests.

The browser is attached in existing-only mode; it is not launched by the bridge. See [BROWSER_SETUP.md](BROWSER_SETUP.md) for setup and verification examples.

## Run and inspect

Start/switch Codex to the bridge:

```bash
codex-uwa
```

Inspect:

```bash
codex-uwa-status
curl -sS http://127.0.0.1:8199/health
```

Stop:

```bash
codex-uwa-stop
```

Restore the official Codex route:

```bash
codex-official
```

The wrapper does not replace Codex authentication.

## Branch discipline

- `standalone-dev`: canonical development and release-candidate branch.
- temporary hardening branches such as `release-hardening-v1`: coordinated pre-release work only.
- `main`: release boundary.
- release tags: immutable public checkpoints.

A temporary hardening branch must return to `standalone-dev` before live candidate evidence is generated. The S3 and office-soak runners deliberately require the canonical candidate branch so temporary work cannot accidentally become release evidence.

Candidate-bound release evidence is invalidated whenever the candidate commit changes, including release-document commits when the release policy requires exact SHA identity.

## Configuration policy

Tracked configuration must contain reusable project defaults only.

Do not put machine-specific conversation URLs, browser/session identifiers, cookies, local workspace paths, or account state into `config/*.json`.

`config/*.local.json` is ignored for local-only files, but adding a new local override format also requires runtime support. Do not assume an ignored filename is automatically loaded.

Private runtime/acceptance state belongs under `~/.uwa`.

## Change workflow

1. Reproduce or define the behavior.
2. Identify the owning layer using [ARCHITECTURE.md](ARCHITECTURE.md).
3. Add or update a focused regression first when practical.
4. Make the smallest change that preserves the trust boundary.
5. Run the focused test set.
6. Run the full suite.
7. Run public-repository safety and dependency checks.
8. If the change touches a release-critical live invariant, regenerate candidate-bound live evidence before release.
9. For release work, use [RELIABILITY_MODEL.md](RELIABILITY_MODEL.md) to determine whether S3, office soak, Desktop E2E, install smoke, or S4 must be regenerated.

Prefer one invariant per change. Avoid combining a browser selector rewrite, compaction rewrite, and tool-policy rewrite in the same fix.

The first RC does not automatically fall back to another provider, local model, or official API. A blocked ChatGPT Web path should produce a clear failure and cleanup rather than a hidden backend switch.

## Debugging

Use sanitized logs and private evidence. Public logs should expose failure class and bounded metadata, not raw prompts/tool content.

Useful surfaces:

- `/health`: listener, request-manager, and sanitized Web readiness.
- `codex-uwa-status`: provider/model/effort and listener ownership.
- private S3/Desktop/install evidence under `~/.uwa`;
- office-work soak evidence under `~/.uwa/standalone-office-soak`;
- release-confidence result under `~/.uwa/standalone-release-confidence`.

For a new maintainer, start with [MAINTAINER_HANDOFF.md](MAINTAINER_HANDOFF.md), [../tests/README.md](../tests/README.md), and [../tools/README.md](../tools/README.md).

If a live gate fails, inspect the exact phase-specific private trace before changing code. Do not diagnose a coarse-turn failure from an unrelated broad log line.

## Compatibility code

Compatibility facades and retained upstream runtime are intentional. Do not delete a large inherited module because it appears unrelated by name alone.

Before pruning:

- confirm it is outside the static closure;
- confirm it is not startup-loaded;
- run the dependency audit;
- run focused and broad tests;
- run live parity if browser/runtime behavior could change.

The first stable release intentionally favors conservative retention over aggressive slimming.
