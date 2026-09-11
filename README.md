# Codex Web Bridge

[中文](README.md) · [English](README.en.md) · [ไทย](README.th.md) · [日本語](README.ja.md) · [한국어](README.ko.md)

Codex Web Bridge 是一个非官方的本地桥接项目，用于把 Codex Desktop / Codex CLI 的模型推理请求路由到已登录的 ChatGPT Web，同时继续让文件、Shell、编辑、测试、Git 等本地工具由 Codex 客户端自身执行。

> 当前状态：S1 和 S2 已关闭，`standalone-dev` 正在进行 S3 独立 CLI/Desktop/live parity 验收。S4 首个 standalone Release 仍然等待 S3 完整关闭。
>
> 最新 S3 检查点：restart continuity、native auto-compaction、Remote V2 compaction、required-tool completion 跨 compaction lineage 的连续性均已在真实链路中证明。当前剩余阻塞位于 post-compaction recovery 的工作区校验阶段。最新一次恢复中 Codex 真实执行了客户端 `exec_command`，但只执行了 `pwd`，没有执行 prompt 要求的完整 marker / `large_context` 目录校验，因此返回 `ACCEPTANCE_WORKSPACE_MISMATCH`。验收工作区本身已确认存在、marker 存在、`large_context` 目录存在。S3 尚未关闭。

## 快速开始

当前开发阶段使用 `standalone-dev`。正式 Release 后会以 `main` 和 Release tag 为准。

```bash
git clone https://github.com/lxxlx2/codex-web-bridge.git
cd codex-web-bridge
git switch standalone-dev
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

## 核心边界

1. Codex 客户端始终是本地执行 authority，Bridge 不越过客户端直接操作用户工作区。
2. provider、model、reasoning effort 必须通过配置、session 与 wire evidence 验证。
3. 显式要求真实工具调用时，文本模拟不能算成功，必须形成真实 `function_call -> local execution -> function_call_output` 往返。
4. same-thread continuation、UWA restart、Web conversation affinity、native/remote compaction 都必须保持逻辑连续性，并在无法证明安全时 fail closed。
5. tool side effect 状态不确定时，不允许无条件自动重放本地工具。
6. private trace 默认只保存验收所需 metadata，公开仓库不接收私人 prompt、命令正文、工具输出、cookies、浏览器 profile 或完整 wire trace。

## S3 当前验收进度

```text
S1 dependency / import / runtime audit           PASS / CLOSED
S2 standalone extraction 与解耦                  PASS / CLOSED
S3 CI + Codex CLI / Desktop / live parity        CURRENT
S4 首个 standalone Release                       PENDING
```

已经在 standalone live path 中证明的项目包括：

```text
repository / local safety gates                  PASS
UWA route = uwa / chatgpt / high                 PASS
真实客户端 exec_command 往返                    PASS
UWA restart 后 same-thread continuity           PASS
native auto-compaction trigger                   PASS
Remote V2 compaction route + completion          PASS
compaction 后 required-tool completion lineage  PASS
request-manager cleanup / healthy listener       PASS
```

当前还没有通过的项目：

```text
post-compaction full recovery                    OPEN
STANDALONE_S3=PASS_LIVE_CLOSED                   NOT YET
```

当前 failure 已从早期的 compaction trigger、重复 compaction、empty output、required-tool replay 等问题收敛到 post-compaction workspace validation。最新恢复轮真实命令为 `/bin/zsh -lc pwd`，工作目录正确指向验收工作区，但模型没有完成同一个 required-tool 指令中后续的 marker 与目录校验，因此验收按设计 fail closed。

在看到完整的：

```text
S3_POST_COMPACTION_RECOVERY=PASS
S3_ROUTE_UWA_CHATGPT_HIGH=PASS
S3_REQUEST_MANAGER_CLEAN=PASS
S3_REPOSITORY_CLEAN_AFTER_LIVE=PASS
STANDALONE_S3=PASS_LIVE_CLOSED
```

之前，不进入 S4，也不发布首个 RC。

## 连续性与长上下文

当前实现覆盖 `previous_response_id`、call-id continuity、Web conversation affinity、private persisted continuity state、native auto-compaction 和 Remote V2 compaction。

Remote V2 compaction 使用受控 envelope，并保留内部 compaction lineage。required-tool completion 只在能够证明属于同一个 compaction lineage 和同一用户轮次时才会复用，避免 compaction 删除 function-call history 后重复强制执行已经完成的本地工具，也避免不同 thread 之间发生状态污染。

当前 standalone catalog 使用经过 live 验证调优的长上下文边界。相关参数仍属于开发期实现细节，后续 Release 可能随着 Codex / ChatGPT Web 行为变化继续调整。

## 已验证的集成基线

第一版 standalone 抽取固定来自：

```text
lxxlx2/universal-web-api@a140002e65a02a3323abcde3e1fdb8674710c996
```

该集成基线已经通过 Stage A-F、真实 client-tool round trip、same-thread/restart continuity、native/remote compaction、Desktop acceptance、stream cancellation cleanup、final regression 和 M1-M7 integrated release gates。

standalone 仓库仍必须独立完成自己的 S3，不能把集成仓库历史结果直接当作 standalone release 证据。

## 开发与发布

开发全部在 `standalone-dev` 进行，`main` 保持发布边界。首个计划版本：

```text
v0.1.0-rc.1
```

只有 RC 在独立仓库通过完整 S3 live parity、安全检查、依赖/provenance 审计和 release artifact 校验后，才会进入正式：

```text
v0.1.0
```

## 安全与隐私

发布目标保持保守默认值：

```text
API bind       127.0.0.1
远程访问        默认关闭
CORS           默认关闭
unsafe Python  关闭
private state  ~/.uwa
```

不要提交账号凭据、cookies、浏览器 profile、私人 prompt、command/tool body、private Responses persistence、原始 browser/session identifier 或完整 wire trace。

安全策略见 [SECURITY.md](SECURITY.md)。

## License、来源与致谢

本项目经由已验证的 `lxxlx2/universal-web-api` 集成版本，派生自 [lumingya/universal-web-api](https://github.com/lumingya/universal-web-api)。继承的 upstream 代码继续遵守 GNU Affero General Public License v3.0 以及适用的版权声明。

详细来源和 attribution 见 [NOTICE.md](NOTICE.md)，完整许可证见 [LICENSE](LICENSE)。

## 免责声明

Codex Web Bridge 是独立的互操作性、学习和工程验证项目，不是 OpenAI、ChatGPT 或 Codex 官方产品，也不代表与 OpenAI 或其他第三方存在合作、授权、认可或背书关系。

项目不会修改或绕过第三方账号权益、订阅限制、配额、模型权限或平台安全控制。使用者需要自行确认其使用方式符合相关软件、网站、服务条款、组织政策和适用法律，并对本地执行的命令、代码变更和外部服务使用负责。
