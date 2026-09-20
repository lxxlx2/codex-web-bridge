# Controlled browser setup

Codex Web Bridge attaches to an already running Chromium-compatible browser through local CDP. The bridge does not launch a browser for you.

Default endpoint:

```text
127.0.0.1:9222
```

Keep the debugging interface on loopback. Do not expose the CDP port to your LAN or the public Internet.

## macOS example

A dedicated browser profile is recommended so normal browsing and the controlled ChatGPT session stay separate:

```bash
mkdir -p "$HOME/.uwa/chrome-profile"

open -na "Google Chrome" --args --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir="$HOME/.uwa/chrome-profile"
```

Open ChatGPT in that browser and log in manually.

## Linux example

Binary names vary by distribution:

```bash
chromium --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir="$HOME/.uwa/chrome-profile"
```

Linux has not yet received the same release-blocking live certification as the primary macOS path.

## Windows example

Adjust the Chrome path as needed:

```powershell
& "$Env:ProgramFiles\Google\Chrome\Application\chrome.exe" --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir="$Env:USERPROFILE\.uwa\chrome-profile"
```

Windows has not yet received the same release-blocking live certification as the primary macOS path.

## Verify CDP

Before starting the bridge:

```bash
curl -sS http://127.0.0.1:9222/json/version
```

A successful JSON response proves that the local CDP endpoint is reachable. It does not prove that ChatGPT is logged in or that the current surface is safe.

Then start/switch the bridge:

```bash
codex-uwa
codex-uwa-status
curl -sS http://127.0.0.1:8199/health
```

The bridge performs its own ChatGPT surface/readiness checks and fails closed on ambiguous, logged-out, quota-blocked, rate-limited, or otherwise unsafe states.

## Privacy

The dedicated profile under `~/.uwa` is local runtime state. Do not copy it into the repository and do not publish cookies, local storage, raw conversation URLs, or browser/session identifiers.

For runtime setup see [DEVELOPMENT.md](DEVELOPMENT.md). For common failures see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
