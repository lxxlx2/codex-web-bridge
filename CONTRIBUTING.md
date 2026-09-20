# Contributing to Codex Web Bridge

Codex Web Bridge is a local interoperability bridge with a deliberately narrow trust boundary: ChatGPT Web provides model inference, while Codex Desktop / CLI remains the authority for workspace, shell, edit, test, Git, sandbox, and approval actions.

Before changing code, read:

- [Architecture](docs/ARCHITECTURE.md)
- [Development guide](docs/DEVELOPMENT.md)
- [Testing guide](docs/TESTING.md)
- [Troubleshooting and engineering decisions](docs/TROUBLESHOOTING.md)
- [Security policy](SECURITY.md)

The documentation index is [docs/README.md](docs/README.md).

## Development branch

Normal development happens on `standalone-dev`. `main` is the release boundary and should only move to a candidate that has completed the documented release gates.

Create focused commits. Avoid unrelated refactors in a bug fix, especially around browser lifecycle, Responses continuation, client-tool policy, compaction, and request cleanup.

## Local setup

Requirements:

- Python 3.10 or newer;
- a local Chromium-compatible browser reachable through the configured CDP port;
- a logged-in ChatGPT Web session in the controlled browser;
- Codex Desktop and/or Codex CLI for real client-tool acceptance.

Recommended developer setup:

```bash
git clone https://github.com/lxxlx2/codex-web-bridge.git
cd codex-web-bridge
git switch standalone-dev

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements-dev.txt

.venv/bin/python tools/install_codex_uwa_commands.py
export PATH="$HOME/bin:$PATH"
```

Common lifecycle commands:

```bash
codex-uwa
codex-uwa-status
codex-uwa-stop
codex-official
```

The default local API endpoint is `http://127.0.0.1:8199`.

## Where to make changes

Use [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) as the code map. The most common paths are:

- Responses protocol and continuation: `app/api/codex_responses_v2.py`, `app/api/codex_runtime.py`;
- ChatGPT Web execution: `app/services/codex_chatgpt_executor.py`;
- client-tool policy: `app/services/client_tool_policy.py`, `app/services/tool_calling*.py`;
- Remote V2 compaction: `app/services/codex_remote_compaction_v2.py`;
- conversation affinity: `app/services/codex_web_session_affinity.py`;
- browser lifecycle and send state: `app/core/stream_monitor.py`, `app/core/workflow/executor_send.py`;
- request cleanup: `app/services/request_manager.py`;
- release/acceptance harnesses: `tools/standalone_*.py`.

Several large browser/config modules are retained from the validated upstream runtime. Their presence does not imply that every upstream provider is part of the supported Codex Web Bridge product surface.

## Test before opening a pull request

At minimum run the tests closest to your change, then the full suite:

```bash
.venv/bin/python -m pytest -q <focused tests>
.venv/bin/python -m pytest -q
```

Also run:

```bash
.venv/bin/python tools/public_repo_safety_check.py
.venv/bin/python tools/standalone_dependency_audit.py
```

Use [docs/TESTING.md](docs/TESTING.md) for the change-to-test map and release-gate rules.

Changes that affect browser lifecycle, continuation, tool calls, compaction, provider routing, install wrappers, security defaults, or release metadata may require real S3/Desktop/install/S4 evidence before release. A historical PASS from another commit does not transfer to a new candidate SHA.

## Security and repository hygiene

Never commit:

- credentials, cookies, browser profiles, or authentication state;
- private prompts, workspace source, command bodies, or tool output;
- raw conversation URLs, thread/session identifiers, private Responses state, or full wire traces;
- `~/.uwa` contents or other local runtime state.

Tracked files under `config/` must contain reusable project defaults only. Machine-specific runtime values belong outside Git.

## Pull requests

A good pull request explains:

1. the observed problem or requested behavior;
2. the root cause or design rationale;
3. the exact files and invariants changed;
4. focused and full test evidence;
5. whether release-bound live evidence is affected;
6. any privacy, security, or migration implications.

Do not weaken a gate merely to make a failing acceptance test pass. If an external condition such as ChatGPT Web rate limiting blocks a live gate, classify it and preserve the correctness criteria.
