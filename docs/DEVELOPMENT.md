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

## 自动模型与思考强度策略 (auto-best / max)

在 standalone 的受控 ChatGPT Web 路径，模型默认从当前账号实际呈现的
`menuitemradio` 可选选项中动态选取。当前策略以 GPT 数字版本优先，
同版本以 Pro、Astra、Sol、Luna 的已知能力系列排序。
页面自身未声明“最强”时，这只是明确、可复现的工程排序策略，
不能视为 OpenAI 官方模型质量排行榜。

默认值为 `UWA_CODEX_WEB_MODEL=auto-best` 和
`UWA_CODEX_REASONING_DEFAULT=max`。`max` 会使用页面实际滑块的
`aria-valuemax`，即便 Codex 请求指定 `high` 也采用最高可验证的 Web 档位；
Codex wire 上的 reasoning effort 保持原样、单独审计。

按需可以设置 `UWA_CODEX_WEB_MODEL=GPT-5.6 Sol` 固定目标，或设置
`UWA_CODEX_REASONING_DEFAULT=high` 以恢复按客户端请求解释 Web 档位的行为。
可见 radio 无法可信区分、缺少 slider metadata、目标 disabled、
出现无法识别的新模型类别或选择后未确认为选中态时默认 fail closed，
不静默切到低版本、不使用官方 API fallback、不发送额外对话。

这是新的 release candidate 源码变更。先在新分支完成回归、CI 与合并，
再重新绑定 exact-SHA S3 / Desktop E2E / 后续 release evidence。
