# Notice and provenance

Codex Web Bridge is a standalone extraction of Codex/ChatGPT-Web interoperability work developed and validated in `lxxlx2/universal-web-api`.

## Upstream foundation

The browser automation, API/runtime foundation and other upstream-derived portions originate from:

- Project: `lumingya/universal-web-api`
- Repository: https://github.com/lumingya/universal-web-api
- License: GNU Affero General Public License v3.0

The standalone extraction is produced from the validated integration baseline:

- Integration repository: `lxxlx2/universal-web-api`
- Baseline commit: `a140002e65a02a3323abcde3e1fdb8674710c996`

The standalone project includes modifications and new Codex-specific compatibility, routing, continuity, compaction, observability, lifecycle and validation work developed in the integration repository.

## License continuity

Files derived from the upstream project remain subject to AGPL-3.0 and applicable copyright notices. The standalone repository must ship the complete AGPL-3.0 license text with every release candidate and release.

S1/S2 extraction may move or narrow upstream-derived code. Refactoring or relocation does not remove the original license obligations.

## Reference implementations and acknowledgements

During development, public Codex/Responses bridge projects and public upstream Codex behavior were studied for interoperability and reliability ideas. Compatibility research does not imply sponsorship or endorsement. Any directly reused third-party code must have compatible licensing and explicit file-level attribution before release.

Special thanks to these public projects for documenting failure modes and reliability patterns around ChatGPT Web automation:

- `leeguooooo/chatgpt-use` — https://github.com/leeguooooo/chatgpt-use — studied for request-economy, account/channel serialization, throttle backoff, submission-unknown semantics and conversation-record recovery ideas.
- `kev489/gpt-tool-use` — https://github.com/kev489/gpt-tool-use — studied for explicit ChatGPT rate-limit dialog detection across send/wait phases and fail-closed handling when the web surface is throttled.

The current Codex Web Bridge guard implementation is independently written for this repository; no source code from those projects is copied into this project by this acknowledgement.

## Independent project

Codex Web Bridge is unofficial. It is not an OpenAI product and is not affiliated with, sponsored by or endorsed by OpenAI.
