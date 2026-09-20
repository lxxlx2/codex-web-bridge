# Codex Web Bridge

[中文](README.md) · [English](README.en.md) · [ไทย](README.th.md) · [日本語](README.ja.md) · [한국어](README.ko.md)

Codex Web Bridge 是一个非官方的本地桥接项目，核心目标只有一个：把 Codex Desktop / Codex CLI 的模型推理请求路由到已登录的 ChatGPT Web，同时继续让文件、Shell、编辑、测试、Git、sandbox 和审批等本地权限完全由 Codex 客户端自身掌控。

首个 RC 只支持这条推理路径：

```text
Codex Desktop / CLI -> Codex Web Bridge -> ChatGPT Web
```

当前不做备用 provider、本地模型或官方 API 自动 fallback。ChatGPT Web、账号额度、浏览器 surface 或路由无法安全继续时，Bridge 明确失败并停止，不会静默换后端继续执行。

> 首个 RC 采用 exact-candidate 发布策略：CI、S3 live、Codex Desktop E2E、clean-install smoke 和 S4 release gate 必须全部绑定到同一个 commit。历史 PASS 不能自动转移到新的代码或文档 commit。
>
> 项目已经建立完整的 release/acceptance 流程。先读 [项目总览](docs/PROJECT_OVERVIEW.md)；开发入口、代码地图、测试矩阵、可靠性模型和维护交接见 [CONTRIBUTING.md](CONTRIBUTING.md)、[docs/README.md](docs/README.md) 与 [docs/MAINTAINER_HANDOFF.md](docs/MAINTAINER_HANDOFF.md)。

## 快速开始

首个 RC 的主要 live 验证平台是 macOS。运行需要 Python 3.10+、Codex Desktop/CLI，以及一个可通过本地 CDP 连接、已经登录 ChatGPT Web 的 Chromium 兼容浏览器。默认 CDP 端口为 `9222`。
Bridge 只连接已经运行的浏览器，不负责自动启动浏览器；首次配置见 [docs/BROWSER_SETUP.md](docs/BROWSER_SETUP.md)。

普通用户从 `main` 或 Release tag 安装；参与开发时再切换到 `standalone-dev`。

```bash
git clone https://github.com/lxxlx2/codex-web-bridge.git
cd codex-web-bridge
python3 tools/install_codex_uwa_commands.py
export PATH="$HOME/bin:$PATH"
```

切换到 Web Bridge：

```bash
codex-uwa
```

切回 Codex 官方路由：

```bash
codex-official
```

查看状态：

```bash
codex-uwa-status
```

停止本地 Bridge：

```bash
codex-uwa-stop
```

默认本地接口：

```text
http://127.0.0.1:8199
```

健康检查：

```bash
curl -sS http://127.0.0.1:8199/health
```

第一次启动可能需要创建项目虚拟环境并安装依赖。浏览器/CDP、ChatGPT 登录状态或页面 surface 不满足要求时，Bridge 会 fail closed，而不会把请求静默发送到错误页面。

## 架构

```text
Codex Desktop / CLI
  负责工作区、Shell、编辑、测试、Git、sandbox、审批
        |
        v
Codex Web Bridge
  负责 Responses 协议兼容、路由、上下文连续性、compaction、浏览器传输
        |
        v
已登录的 ChatGPT Web 会话
```

浏览器页面不会直接获得本地文件系统权限。需要真实本地工具时，Bridge 返回标准 Responses `function_call`，由 Codex 客户端在本地执行，再把 `function_call_output` 送回模型继续当前 turn。

受控 UWA 路由当前默认值：

```text
provider = uwa
model = chatgpt
reasoning effort = high
```

主调用链、continuation/affinity/compaction、compatibility facade 和 inherited runtime 的边界见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 核心边界

1. Codex 客户端始终是本地执行 authority，Bridge 不越过客户端直接操作用户工作区。
2. provider、model、reasoning effort 必须通过配置、session 与 wire evidence 验证。
3. 显式要求真实工具调用时，文本模拟不能算成功，必须形成真实 `function_call -> local execution -> function_call_output` 往返。
4. same-thread continuation、UWA restart、Web conversation affinity、native/remote compaction 都必须保持逻辑连续性，并在无法证明安全时 fail closed。
5. tool side effect 状态不确定时，不允许无条件自动重放本地工具。
6. private trace 默认只保存验收所需 metadata，公开仓库不接收私人 prompt、命令正文、工具输出、cookies、浏览器 profile、原始 conversation/thread/session identifier 或完整 wire trace。
7. tracked `config/` 只保存可复用默认配置；机器自己的 conversation URL、route group、tab exclusion 等本地状态不得提交。

## RC 验收要求

首个 RC 的 release evidence 必须全部绑定到同一个 candidate commit，而且不会把一次偶然成功当成发布可靠性：

```text
S1 / S2                                         PASS / CLOSED
standalone deterministic regression             PASS
exact-SHA CI                                    PASS
clean-checkout install / rollback smoke         PASS
S3 full live PASS_LIVE_CLOSED                   >= 3 次，同一 SHA
S3 successful evidence windows                  >= 2 个两小时 UTC window
S3 first-to-last successful span                 >= 7200 秒
office-work soak + effect verification          PASS，同一 SHA
release confidence aggregate                    PASS，同一 SHA
Codex Desktop E2E                               PASS，同一 SHA
S4 docs/version/security/provenance              PASS，同一 SHA
main CI                                         PASS BEFORE TAG
tagged-source smoke                             PASS BEFORE GITHUB RELEASE
```

S3 负责 restart、native/remote compaction、post-compaction recovery、route 和 request cleanup；office-work soak 负责多文件修改、真实失败后修复、Git diff 约束、交互进程等日常工作型任务，并由 checker 独立验证实际文件、测试和 diff 结果；Desktop E2E 再补真实桌面端路径。

外部 ChatGPT Web rate limit/quota/auth/challenge 会让当前 live run 明确 FAIL 并停止。这种外部失败不自动判定 candidate 代码有 bug，但也不计入所需的成功次数。

完整测试层级见 [docs/TESTING.md](docs/TESTING.md)，为什么需要重复 live evidence 与 effect verification 见 [docs/RELIABILITY_MODEL.md](docs/RELIABILITY_MODEL.md)。

## 连续性与长上下文

当前实现覆盖 `previous_response_id`、call-id continuity、Web conversation affinity、private persisted continuity state、native auto-compaction 和 Remote V2 compaction。

Remote V2 compaction 使用受控 envelope，并保留内部 compaction lineage。required-tool completion 只在能够证明属于同一个 compaction lineage 和同一用户轮次时才会复用，避免 compaction 删除 function-call history 后重复强制执行已经完成的本地工具，也避免不同 thread 之间发生状态污染。

当前 standalone catalog 使用经过 live 验证调优的长上下文边界。相关参数仍属于实现细节，后续 Release 可能随着 Codex / ChatGPT Web 行为变化继续调整。

历史 live 问题、真实根因和对应回归测试的索引见 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)。

## 已验证的集成基线

第一版 standalone 抽取固定来自：

```text
lxxlx2/universal-web-api@a140002e65a02a3323abcde3e1fdb8674710c996
```

该集成基线通过了 Stage A-F、真实 client-tool round trip、same-thread/restart continuity、native/remote compaction、Desktop acceptance、stream cancellation cleanup、final regression 和 M1-M7 integrated release gates。

这些历史结果只用于 provenance 和设计基线。standalone 每个 release candidate 都必须在自己的 exact commit 上重新生成 release evidence。

仓库中仍保留一部分经过 dependency/runtime closure 证明必要的 upstream browser/config/media runtime；这不代表所有 upstream provider 都是 Codex Web Bridge 的公开支持面。后续精简计划见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## 开发与发布

普通开发在 `standalone-dev` 进行，`main` 是发布边界，Release tag 是不可变公开 checkpoint。首个计划版本：

```text
v0.1.0-rc.1
```

RC 发布后进入观察和兼容性反馈阶段；若需要修改 RC 源码则递增 RC 后缀。没有未解决 release blocker 后再进入：

```text
v0.1.0
```

参与开发请从 [CONTRIBUTING.md](CONTRIBUTING.md) 开始；接手维护建议直接读 [docs/MAINTAINER_HANDOFF.md](docs/MAINTAINER_HANDOFF.md)。本地环境和配置规则见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)，测试文件地图见 [tests/README.md](tests/README.md)，发布/验收工具地图见 [tools/README.md](tools/README.md)，发布后的工作计划见 [docs/ROADMAP.md](docs/ROADMAP.md)。

RC 的平台、浏览器/CDP、账号配额和 retained runtime 限制见 [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md)。

## 安全与隐私

发布目标保持保守默认值：

```text
API bind       127.0.0.1
远程访问        默认关闭
CORS           默认关闭
unsafe Python  关闭
private state  ~/.uwa
```

不要提交账号凭据、cookies、浏览器 profile、私人 prompt、command/tool body、private Responses persistence、原始 conversation/thread/session identifier、conversation URL 或完整 wire trace。

安全策略见 [SECURITY.md](SECURITY.md)。

## License、来源与致谢

本项目经由已验证的 `lxxlx2/universal-web-api` 集成版本，派生自 [lumingya/universal-web-api](https://github.com/lumingya/universal-web-api)。继承的 upstream 代码继续遵守 GNU Affero General Public License v3.0 以及适用的版权声明。

详细来源和 attribution 见 [NOTICE.md](NOTICE.md)，完整许可证见 [LICENSE](LICENSE)。

## 免责声明

Codex Web Bridge 是独立的互操作性、学习和工程验证项目，不是 OpenAI、ChatGPT 或 Codex 官方产品，也不代表与 OpenAI 或其他第三方存在合作、授权、认可或背书关系。

项目不会修改或绕过第三方账号权益、订阅限制、配额、模型权限或平台安全控制。使用者需要自行确认其使用方式符合相关软件、网站、服务条款、组织政策和适用法律，并对本地执行的命令、代码变更和外部服务使用负责。
