# Known limitations

These limitations apply to the first standalone release candidate unless a later release says otherwise.

## ChatGPT Web dependency

Codex Web Bridge depends on ChatGPT Web DOM and behavior. UI changes, authentication challenges, new quota surfaces, or changed streaming behavior can break automation even when the local API remains unchanged.

The bridge deliberately fails closed on ambiguous or unsafe Web state.

## Account limits remain account limits

The project does not increase, bypass, or evade ChatGPT message limits, model entitlements, Work quotas, or rate limits.

Rate-limit handling is bounded detection, acknowledgement cleanup where safe, pacing, and failure classification. It is not quota evasion.

## Primary live-certified platform

The first RC's strongest live evidence is macOS with Codex Desktop/CLI and a local Chromium-compatible browser. Windows/Linux runtime code is retained where supported, but they do not yet have equivalent release-blocking live certification.

## Browser/CDP requirement

The Web-backed path requires a controlled Chromium-compatible browser reachable over local CDP, default port `9222`, with a usable logged-in ChatGPT Web session.

The release defaults remain loopback-only.

## RC compatibility surface

`v0.1.0-rc.1` is a release candidate. Internal implementation details, Web selectors, long-context thresholds, and retained upstream runtime may still change before stable `v0.1.0`.

## Retained upstream runtime

The repository still contains generic browser/config/media infrastructure from the validated Universal Web API baseline because dependency/runtime closure and live parity require conservative retention.

That code is implementation inheritance, not a promise that every upstream Web provider is a supported Codex Web Bridge feature.

## No direct browser filesystem authority

ChatGPT Web never receives direct local filesystem or shell authority from this bridge. Real local tools remain Codex client tools and are subject to Codex sandbox/approval behavior.

## Remote exposure

Remote API exposure is not a first-RC default. Loopback binding, CORS-off, and unsafe-Python-off are the conservative defaults. Users who deliberately enable remote access are responsible for the additional authentication/network boundary.

## Support and diagnostics

Public bug reports must be sanitized. Do not publish private prompts, command/tool bodies, conversation URLs, thread/session identifiers, cookies, browser profiles, or full private traces.

Use [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for known failure signatures and [../SECURITY.md](../SECURITY.md) for disclosure rules.
