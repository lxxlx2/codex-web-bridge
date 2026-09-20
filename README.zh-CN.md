# Codex Web Bridge

[中文](README.md) · [English](README.en.md) · [ไทย](README.th.md) · [日本語](README.ja.md) · [한국어](README.ko.md)

> 主中文文档维护在 [README.md](README.md)。本文件保留简体中文入口，并同步当前 standalone 状态。

Codex Web Bridge 是一个非官方本地桥接项目，用于把 Codex Desktop / Codex CLI 的模型推理请求路由到已登录的 ChatGPT Web，同时继续让工作区访问、Shell、编辑、测试、Git、sandbox 和审批由 Codex 客户端自身负责。

## 当前状态

首个 RC 采用 exact-candidate 发布策略。CI、S3 live、Codex Desktop E2E、clean-install smoke 和 S4 release gate 必须全部对应同一个 release commit；代码或文档改变 HEAD 后，受影响的 candidate-bound evidence 必须重新生成。

开发入口、架构、测试矩阵和历史问题索引见 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [docs/README.md](docs/README.md)。

## 快速开始

普通用户使用 `main` 或 Release tag；参与开发时使用 `standalone-dev`。首个 RC 主要 live 验证平台为 macOS，运行需要 Python 3.10+、Codex Desktop/CLI，以及可通过本地 CDP 连接且已登录 ChatGPT Web 的 Chromium 兼容浏览器。

```bash
git clone https://github.com/lxxlx2/codex-web-bridge.git
cd codex-web-bridge
python3 tools/install_codex_uwa_commands.py
export PATH="$HOME/bin:$PATH"
```

常用命令：

```bash
codex-uwa
codex-uwa-status
codex-uwa-stop
codex-official
```

默认本地接口：

```text
http://127.0.0.1:8199
```

## 架构

```text
Codex Desktop / CLI
  工作区、Shell、编辑、测试、Git、sandbox、审批
        |
        v
Codex Web Bridge
  Responses 兼容、路由、连续性、compaction、浏览器传输
        |
        v
已登录的 ChatGPT Web 会话
```

浏览器不会直接获得本地文件系统权限。真实本地工具仍以 Responses `function_call` 形式返回给 Codex 客户端执行，再由客户端把 `function_call_output` 送回当前 turn。

当前受控路由：

```text
provider = uwa
model = chatgpt
reasoning effort = high
```

## 连续性与 compaction

项目覆盖 `previous_response_id`、call-id continuity、Web conversation affinity、private continuity state、native auto-compaction 和 Remote V2 compaction。

Remote V2 compaction envelope 带有内部 lineage。required-tool completion 只有在能够证明属于同一个 compaction lineage 和同一用户轮次时才会复用，从而避免压缩历史后重复执行已经完成的本地工具，也避免不同 thread 之间相互污染。

## 发布边界

开发在 `standalone-dev` 进行，`main` 保持发布边界。计划中的第一个候选版本是：

```text
v0.1.0-rc.1
```

只有当 S3 完整输出 `STANDALONE_S3=PASS_LIVE_CLOSED`，并继续通过 release artifact、安全、依赖和 provenance 检查后，才会进入正式 `v0.1.0`。

## 安全与隐私

```text
API bind       127.0.0.1
远程访问        默认关闭
CORS           默认关闭
unsafe Python  关闭
private state  ~/.uwa
```

不要提交凭据、cookies、浏览器 profile、私人 prompt、command/tool body、private Responses persistence、原始 browser/session identifier 或完整 wire trace。

安全策略见 [SECURITY.md](SECURITY.md)。

## License 与来源

本项目经由已验证的 `lxxlx2/universal-web-api` 集成版本，派生自 [lumingya/universal-web-api](https://github.com/lumingya/universal-web-api)。继承的 upstream 代码继续遵守 GNU Affero General Public License v3.0 以及适用的版权声明。

详细来源见 [NOTICE.md](NOTICE.md)，完整许可证见 [LICENSE](LICENSE)。

## 非官方项目声明

Codex Web Bridge 是独立的互操作性、学习和工程验证项目，不是 OpenAI、ChatGPT 或 Codex 官方产品，也不代表存在合作、授权、认可或背书关系。项目不会修改或绕过第三方账号权益、订阅限制、配额、模型权限或平台安全控制。
