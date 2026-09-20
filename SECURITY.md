# Security policy

Codex Web Bridge is designed as a local bridge. The release target binds locally by default and keeps browser/session state private.

## Sensitive data

Do not commit or publish:

- account credentials, cookies, authentication tokens or API keys;
- browser profiles, raw browser/session identifiers, or copied conversation URLs;
- private prompts, source snippets copied from private workspaces, command bodies or tool output;
- private Responses persistence, full wire traces or debug captures;
- local absolute paths that expose personal usernames when a sanitized path is sufficient.

Private runtime and diagnostic state should remain under `~/.uwa` or another user-controlled local location excluded from Git.

Tracked files under `config/` must contain reusable project defaults only. Machine-specific tab exclusions, remembered route groups, conversation URLs, browser/session identifiers, or other local browser state must not be committed. The public-repository safety scanner rejects known conversation-URL forms in tracked text.

## Network defaults

The release candidate must bind its local control API to `127.0.0.1` by default and keep other control surfaces loopback-only unless a user explicitly opts into remote access. CORS, unsafe Python execution and remote exposure must not silently enable themselves.

## Tool authority

ChatGPT Web does not receive direct filesystem or shell authority from this bridge. Local client tools such as `exec_command` are executed by Codex Desktop/CLI under the client's sandbox and approval policy. The bridge only transports compatible Responses function-call state.

## Reporting a vulnerability

Report security issues privately to the repository owner or through GitHub private vulnerability reporting when it is enabled for this repository. Do not open a public issue containing credentials, private logs, exploit payloads that expose user data, raw conversation/session identifiers, or other sensitive material.

The first public release supports the release-tagged source and the current `main` line on a best-effort basis. Security fixes may require upgrading to a newer release candidate or patch release.
