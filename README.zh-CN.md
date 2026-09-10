# Codex Web Bridge

> 主中文文档现在维护在 [README.md](README.md)。本文件保留早期 standalone 中文说明，避免历史链接失效。

[English](README.en.md)

Codex Web Bridge 是一个非官方的本地桥接项目，用于把 Codex Desktop / Codex CLI 的模型推理请求路由到 ChatGPT Web，同时继续让本地工具由 Codex 客户端自身执行。

> 当前状态：`standalone-dev` 正在进行独立仓库抽取和发布前收口。集成版本已经在 `lxxlx2/universal-web-api` 完成 M1-M7 全部发布门槛；这个仓库用于形成更干净的 standalone 版本，目前还没有打正式 Release 标签。

## 架构

```text
Codex Desktop / CLI
  负责本地工作区、Shell、编辑、测试、Git、sandbox 和审批
        |
        v
Codex Web Bridge
  负责 Responses 兼容、路由、连续性、compaction 和浏览器传输
        |
        v
已登录的 ChatGPT Web 会话
```

浏览器页面不会直接获得本地文件系统权限。本地 `exec_command` 等工具仍由 Codex 客户端按照自己的 sandbox 和 approval policy 执行。

## 已验证的集成基线

第一版 standalone 抽取固定基于：

```text
lxxlx2/universal-web-api@a140002e65a02a3323abcde3e1fdb8674710c996
```

该集成基线已经完成协议和 CLI 验收、真实本地工具往返、同线程和重启连续性、native/remote compaction、Desktop 验收、流取消清理、最终回归、公开仓库安全检查以及 merge-to-main 门槛。

## Standalone 发布路线

```text
S1 依赖/import/runtime 审计          进行中
S2 独立抽取和解耦                    下一阶段
S3 CI + CLI/Desktop/live 等价验收     待进行
S4 首个 standalone Release           待进行
```

开发全部在 `standalone-dev` 进行。默认 `main` 继续作为发布边界，只有 standalone release candidate 通过完整验收后才会合并。

## 生成保守的 S2 候选树

仓库提供了一个受保护的抽取脚本。它从已经验证的源基线计算 Codex bridge 入口的本地 Python import closure，同时加入已知 import-time side effect、发布验收测试和必要配置候选，然后记录源 commit 和复制文件 manifest。

```bash
python3 tools/bootstrap_from_uwa.py --commit --push
```

首次生成的树会刻意偏大。S2 会继续把通用 Universal Web API 耦合拆掉，只有在测试能证明更小的树仍保持功能正确时才删除代码。

## 计划保留的能力

最终 standalone release candidate 预计保留 Codex Responses bridge、ChatGPT Web 传输、Web 模型/推理强度校验、本地工具协议、continuation persistence、Web conversation affinity、remote compaction、stream compatibility、provider switching/lifecycle helper、发布验收，以及这些能力真正需要的最小 browser/config runtime。

通用 provider API、dashboard、无关 parser/provider registry、updater surface 和历史 milestone 工具会在 standalone parity 证明无依赖后逐步移除。

## 安全默认值

发布目标继续保持保守默认值：

```text
API bind       127.0.0.1
远程访问        默认关闭
CORS           默认关闭
unsafe Python  关闭
私有状态        ~/.uwa
```

禁止提交账号凭据、cookies、浏览器 profile、私人 prompt、command/tool body、private Responses persistence、原始 browser/session identifier 或完整 wire trace。

安全策略见 [SECURITY.md](SECURITY.md)。

## License 和来源说明

这个 standalone 项目经由已验证的 `lxxlx2/universal-web-api` 集成版本，派生自 `lumingya/universal-web-api`。继承的 upstream 代码继续遵守 GNU Affero General Public License v3.0 及适用的版权声明。

详细 provenance 见 [NOTICE.md](NOTICE.md)。完整 AGPL-3.0 文本会在 bootstrap 时从验证基线复制进仓库，并且必须保留在 release candidate 中。

## 非官方项目声明

这是一个独立的互操作性和工程验证项目，不是 OpenAI、ChatGPT 或 Codex 官方产品，也不代表合作、授权或背书。项目不会修改第三方账号权益、订阅限制、配额或模型可用性。使用者需要自行遵守相关软件、网站、服务条款和适用法律。
