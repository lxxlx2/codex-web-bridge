# Codex Web Bridge

[English](README.en.md)

Codex Web Bridge 是一个非官方的本地桥接项目，用于把 Codex Desktop / Codex CLI 的模型推理请求路由到已登录的 ChatGPT Web，同时继续让文件、Shell、编辑、测试、Git 等本地工具由 Codex 客户端自身执行。

> 当前状态：standalone 的 S1 依赖审计与 S2 抽取解耦已经关闭，`standalone-dev` 进入 S3 独立 CLI/Desktop/live parity 验收。已验证的集成版本在 `lxxlx2/universal-web-api` 完成了 M1-M7 全部门槛；本仓库尚未发布正式 Release。

## 快速开始

当前开发阶段使用 `standalone-dev`。正式 Release 后会以 `main` 和 Release tag 为准。

```bash
git clone https://github.com/lxxlx2/codex-web-bridge.git
cd codex-web-bridge
git switch standalone-dev
python3 tools/install_codex_uwa_commands.py
export PATH="$HOME/bin:$PATH"
```

启动并切换到 Web Bridge 路由：

```bash
codex-uwa
```

恢复 Codex 官方账号默认路由：

```bash
codex-official
```

查看当前 provider 和本地 Bridge 状态：

```bash
codex-uwa-status
```

只停止本地 Bridge 服务：

```bash
codex-uwa-stop
```

这四个命令是推荐的日常入口。`codex-uwa` 会写入受控的 UWA provider 配置、启动本地 Bridge，并重新打开 Codex Desktop；`codex-official` 会恢复进入 UWA 前保存的相关配置、停止本地 listener，并重新打开 Codex Desktop。账号登录状态不会被修改。

如果不希望安装快捷命令，也可以直接调用底层工具：

```bash
python3 tools/codex_provider_switch.py uwa
python3 tools/codex_provider_switch.py official
python3 tools/codex_provider_switch.py status
python3 tools/codex_uwa_lifecycle.py status
```

默认本地接口：

```text
http://127.0.0.1:8199
```

健康检查：

```bash
curl -sS http://127.0.0.1:8199/health
```

## 它解决什么问题

Codex Desktop / CLI 很适合承担本地 coding agent 的职责：读取工作区、执行 Shell、修改代码、运行测试、操作 Git，并遵守本地 sandbox 和 approval policy。

Codex Web Bridge 把“模型推理”和“本地执行”拆开：

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

## 核心设计

项目坚持几个边界：

1. Codex 客户端始终是本地执行 authority，Bridge 不越过客户端直接操作用户工作区。
2. UWA 路由的 provider、model、reasoning effort 必须可验证，不能只相信 UI 标签。
3. 显式要求真实工具调用时，文本模拟不能算成功，必须形成真实 `function_call -> local execution -> function_call_output` 往返。
4. 同一 thread、重启、Web conversation affinity 丢失和 remote compaction 后，都优先保证逻辑连续性和 fail-closed 行为。
5. stream cancellation、generator close 或客户端断开时，pending backing task 必须 cancel 并 await，避免遗留浏览器请求。
6. metadata helper 与真实 agent turn 分离，标题等隐藏辅助请求不会误进入编码 lane、required-tool 检测或正式 route accounting。
7. 私有 trace 默认只记录验证协议所需的 metadata，不保存 prompt、源码、命令正文和工具输出。

受控 UWA 路由的当前默认值：

```text
provider = uwa
model = chatgpt
reasoning effort = high
```

## Responses 与本地工具流程

```text
Codex Desktop / CLI
        |
        v
OpenAI Responses request
        |
        v
Codex Web Bridge
        |
        v
ChatGPT Web
        |
        v
Responses function_call
        |
        v
Codex 本地执行工具
        |
        v
function_call_output
        |
        v
Responses continuation
        |
        v
response.completed
```

Bridge 不会把网页中的纯文本工具样例当成已经执行的本地动作，也不会在无法确认副作用状态时无条件重复执行工具。

## 连续性与长上下文

当前实现覆盖 `previous_response_id`、call-id continuity、Web conversation affinity、private persisted continuity state、native auto-compaction 和 remote V2 compaction。

当浏览器 conversation mapping 因重启或过期而丢失时，系统会尝试从受控的本地状态恢复逻辑上下文。恢复失败时优先停止或重建安全路径，不强制复用一个已经无法证明正确的旧会话。

compaction summary 会区分已经完成的历史请求和当前 active goal，避免压缩后把旧任务重新变成待执行指令。

## 已验证的集成基线

第一版 standalone 抽取固定来自：

```text
lxxlx2/universal-web-api@a140002e65a02a3323abcde3e1fdb8674710c996
```

该基线已经通过：

```text
Stage A-F protocol / CLI acceptance             PASS
真实 function_call / exec_command 往返          PASS
同 thread continuation                          PASS
UWA restart 后 same-thread continuity           PASS
native / remote compaction                      PASS
metadata-helper isolation                       PASS
Hybrid H0-H5                                    PASS
Codex Desktop D1-D5                             PASS
stream cancellation cleanup                     PASS
201 项 Codex final regression                   PASS
M1-M7 integrated release gates                  PASS / CLOSED
```

完整 standalone 版本会再次独立执行自己的 S3 parity acceptance，不能只依赖集成仓库历史结果。

## Standalone 开发与发布进度

```text
S1 dependency / import / runtime audit           PASS / CLOSED
S2 standalone extraction 与解耦                  PASS / CLOSED
S3 CI + Codex CLI / Desktop / live parity        CURRENT
S4 首个 standalone Release                       PENDING
```

开发全部在 `standalone-dev` 进行，`main` 保持发布边界。只有 standalone release candidate 完整通过安全检查、依赖审计、单元/回归测试以及真实 Codex CLI/Desktop 验收后，才会进入 `main` 和首个 Release。

S2 已完成 Codex-only entrypoint、Responses runtime seam、ChatGPT Web executor、standalone Responses fallback、通用 API/parser 启动边界收缩和审计驱动的最终 pruning。最新依赖审计只剩 `security_guard.py` 位于 runtime closure 外，该文件因 public/release safety gate 被有意保留。详细证据见 `docs/STANDALONE_S2_CLOSURE_2026-09-10.md`。

## 开发与测试流程

项目采用“先证明，再精简”的方式：

```text
固定已验证 source baseline
        |
        v
静态 import closure + runtime/profile audit
        |
        v
保守 standalone candidate
        |
        v
逐项解除 generic UWA coupling
        |
        v
py_compile + unit/regression + public safety CI
        |
        v
真实 UWA / ChatGPT Web / Codex CLI 验收
        |
        v
Codex Desktop same-thread / restart / tool-call parity
        |
        v
Release Candidate
        |
        v
main + GitHub Release
```

开发中的审计结果、source baseline 和候选 manifest 会留在仓库中，方便其他开发者理解某个模块为什么保留或为什么删除。

## Provider 切换与恢复

切换到 Web Bridge：

```bash
codex-uwa
```

切回官方模式：

```bash
codex-official
```

`codex-official` 的目标是恢复用户在进入 UWA 前的非模型配置，并移除 UWA 使用时添加的 provider/model/reasoning pins。UWA provider 定义可以继续保留，从而让下次切回 Web Bridge 更快。认证信息不会由 Bridge 修改。

## 安全与隐私

发布目标采用保守默认值：

```text
API bind       127.0.0.1
远程访问        默认关闭
CORS           默认关闭
unsafe Python  关闭
private state  ~/.uwa
```

不要提交账号凭据、cookies、浏览器 profile、私人 prompt、命令/工具正文、private Responses persistence、原始 browser/session identifier 或完整 wire trace。

metadata-only Codex wire trace 只用于证明 route、response status、function-call name 等协议事实。完整 capture 可能包含私人数据，不应进入公开仓库。

安全策略和漏洞报告方式见 [SECURITY.md](SECURITY.md)。

## License、来源与致谢

本项目经由已验证的 `lxxlx2/universal-web-api` 集成版本，派生自 [lumingya/universal-web-api](https://github.com/lumingya/universal-web-api)。继承的 upstream 代码继续遵守 GNU Affero General Public License v3.0 以及适用的版权声明。

感谢 upstream 项目提供浏览器自动化、API/runtime 和跨平台基础；同时感谢公开的 Codex、Responses bridge、agent workflow 和 interoperability 项目提供可对照的工程思路。我们会把真正复用的代码和受许可证约束的内容明确记录，单纯参考设计的项目不会被描述成代码来源。

详细来源、修改关系和 attribution 见 [NOTICE.md](NOTICE.md)。完整许可证见 [LICENSE](LICENSE)。

## 免责声明

Codex Web Bridge 是独立的互操作性、学习和工程验证项目，不是 OpenAI、ChatGPT 或 Codex 官方产品，也不代表与 OpenAI 或其他第三方存在合作、授权、认可或背书关系。

项目不会修改或绕过第三方账号权益、订阅限制、配额、模型权限或平台安全控制。网页结构、第三方客户端行为和服务接口可能随时变化，因此任何基于浏览器自动化的能力都存在兼容性变化风险。

使用者需要自行确认其使用方式符合相关软件、网站、服务条款、组织政策和适用法律，并对本地执行的命令、代码变更和外部服务使用负责。

## Release 计划

首次 standalone 版本计划先发布：

```text
v0.1.0-rc.1
```

只有 RC 在独立仓库通过完整 S3 live parity、安全检查、依赖/provenance 审计和 release artifact 校验后，才会发布：

```text
v0.1.0
```

Release 会包含版本说明、CHANGELOG、source snapshot、依赖信息、校验信息和已验证环境说明。开发分支的中间产物不作为正式 Release。