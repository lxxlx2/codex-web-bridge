# Security policy

Codex Web Bridge is designed as a local bridge. The release target binds locally by default and keeps browser/session state private.

## Sensitive data

Do not commit or publish:

- account credentials, cookies, authentication tokens or API keys;
- browser profiles or raw browser/session identifiers;
- private prompts, source snippets copied from private workspaces, command bodies or tool output;
- private Responses persistence, full wire traces or debug captures;
- local absolute paths that expose personal usernames when a sanitized path is sufficient.

Private runtime and diagnostic state should remain under `~/.uwa` or another user-controlled local location excluded from Git.

## Network defaults

The release candidate must keep loopback-only control surfaces and conservative defaults unless a user explicitly opts into remote access. CORS, unsafe Python execution and remote exposure must not silently enable themselves.

## Tool authority

ChatGPT Web does not receive direct filesystem or shell authority from this bridge. Local client tools such as `exec_command` are executed by Codex Desktop/CLI under the client's sandbox and approval policy. The bridge only transports compatible Responses function-call state.

## Reporting a vulnerability

Before the repository becomes public, report security issues privately to the repository owner. Do not open a public issue containing credentials, private logs, exploit payloads that expose user data, or other sensitive material.

After the first public release, this file will be updated with the final private disclosure channel and supported-version policy.
