# Codex Web Bridge v0.1.0-rc.1 发布前剩余需求

> Approved release-specification record. Descriptions of a gate being “current” are historical context from the planning stage; publishability is determined only by exact-candidate evidence and the release sequence in `docs/RELEASE_PROCESS.md`.\n\n
**文档状态**：Approved v1.0  
**目标分支**：`standalone-dev`  
**批准基线**：`de41c61347a71901b8116617e805de8e02aed372`  
**目标版本**：`v0.1.0-rc.1`  
**范围终点**：首个 standalone Release Candidate 发布完成  
**审批状态**：`REQUIREMENTS_APPROVED=YES`

本需求文档批准并冻结后，先完成并评审 `docs/RELEASE_TECHNICAL_DESIGN.md`。技术设计批准前，不继续新增发布相关生产代码修改。

## 1. 背景

Codex Web Bridge 已完成 S1 依赖/import/runtime 审计和 S2 standalone 抽取与解耦，当前处于 S3 CLI/Desktop/live parity 收口阶段。

最近几轮真实 S3 验收暴露出一个流程问题：代码修复、环境问题、验收脚本问题和发布要求混在同一条调试链路里，导致需求边界不断变化，出现“发现一个问题、立即修一个问题、重新跑长链路、再发现新问题”的循环。

从现在开始，发布前工作改为正式的需求、设计、实现、验收四阶段流程：

1. 需求文档确认并冻结。
2. 技术设计确认并冻结。
3. 仅按已批准设计实施。
4. 按固定验收矩阵一次性收口 S3/S4。

任何超出本文档范围的新需求，都不能直接进入实现，必须先修改本文档并重新评审。

## 2. 发布目标

`v0.1.0-rc.1` 的目标是交付一个可重复安装、可回退、可诊断、默认安全的本地 Codex Web Bridge，使 Codex Desktop / Codex CLI 能通过已登录的 ChatGPT Web 完成模型推理，同时继续由 Codex 客户端负责本地文件、Shell、编辑、测试、Git、sandbox 和审批。

RC 必须证明：

- standalone 仓库可以独立运行，不依赖原 `universal-web-api` 工作目录；
- Codex 的 Responses 链路、真实本地工具往返、same-thread continuity、restart continuity、native/remote compaction 和 post-compaction recovery 在真实环境中成立；
- ChatGPT Web 页面处于异常状态时，系统会 fail closed，不会把验收请求误发到错误 surface，也不会无限重试；
- 安装、切换、运行、停止、回退、诊断均有稳定命令；
- release tree 不包含私人运行数据、账号状态、cookie、prompt、tool body、wire trace 等敏感内容；
- 文档、版本号、CHANGELOG、NOTICE、SECURITY 和 Release Notes 与发布内容一致。

## 3. 本次 RC 的范围

### R1. Standalone 独立运行

RC 必须从 `codex-web-bridge` 自身启动和运行，不得要求用户保留 `~/universal-web-api` 才能工作。

必须支持：

```text
codex-uwa
codex-uwa-status
codex-uwa-stop
codex-official
```

安装后的 wrapper、listener、配置和生命周期命令必须指向当前 standalone checkout。

### R2. Codex 本地工具权限边界

ChatGPT Web 不得直接获得用户本地文件系统或 Shell 权限。

本地工具调用必须保持：

```text
model function_call
-> Codex Desktop / CLI 本地执行
-> function_call_output
-> 同一 turn 继续
```

当验收明确要求真实工具调用时，文本模拟不能算成功。

### R3. Provider / Model / Effort 路由

RC 的受控验收路由固定为：

```text
provider = uwa
model = chatgpt
reasoning effort = high
```

必须通过配置、session/rollout 和 UWA wire/runtime metadata 三类证据证明路由正确。证据不一致时 fail closed。

### R4. Same-thread continuity

同一 Codex thread 在普通多轮、UWA restart、`previous_response_id` continuation、browser conversation affinity、native auto-compaction、Remote V2 compaction 和 post-compaction recovery 中必须保持逻辑连续。

不能通过创建新的逻辑 thread 伪造成功。

### R5. Required-tool 与副作用安全

required tool completion 只能在能够证明属于同一 thread、同一用户轮次、同一 compaction lineage 时复用。

如果本地工具是否已执行无法证明，系统不得无条件自动重放有副作用的工具。

提交状态未知时不得盲目重复发送。

### R6. ChatGPT Web surface 安全

所有自动验收和正式运行都必须明确区分 ChatGPT Web 的可用 surface。

在开始昂贵的 live/compaction 验收前，必须确认：

- 浏览器连接正常；
- request manager 没有遗留 running request；
- 当前受控 ChatGPT target 可唯一确定；
- 当前 surface 是普通聊天 surface，不是 Work/工作 surface；
- composer 没有上一轮残留输入；
- 当前没有 Work quota exhausted；
- 当前没有普通 usage exhausted；
- 当前没有 rate-limit/too-many-requests 阻断；
- 当前没有登录失效、挑战页或明显不可发送状态。

任一条件不满足时，必须在进入长上下文 probe 前 fail fast，并给出明确 failure class。

验收不得把 S3 prompt 发送到 Work surface、项目任务页或上一轮残留会话。

### R7. ChatGPT Web 限流处理

检测到 ChatGPT Web 429/Too Many Requests/请求过于频繁后：

- 当前请求停止自动重复点击发送；
- 进入明确的 throttle/cooldown 状态；
- 请求以标准、可识别的终止错误结束；
- request manager 和 tab/session 在有界时间内收尾；
- 不再出现已识别限流后仍保持 busy 约 600 秒才被 watchdog 清理；
- 不通过规避平台限额来“通过验收”。

### R8. S3 live parity 验收

S3 的最终关闭必须由一次完整、无人工干预的 standalone runner 产生。

必须同时输出：

```text
S3_REPO_PREFLIGHT=PASS
S3_LOCAL_SAFETY_REGRESSION=PASS
S3_UWA_HEALTH=PASS
S3_REAL_CLIENT_TOOL=PASS
S3_SAME_THREAD_RESTART_RECOVERY=PASS
S3_NATIVE_AUTO_COMPACTION=PASS
S3_REMOTE_V2_COMPACTION=PASS
S3_POST_COMPACTION_RECOVERY=PASS
S3_ROUTE_UWA_CHATGPT_HIGH=PASS
S3_REQUEST_MANAGER_CLEAN=PASS
S3_REPOSITORY_CLEAN_AFTER_LIVE=PASS
STANDALONE_S3=PASS_LIVE_CLOSED
```

S3 runner 还必须满足：

- preflight 失败时不进入昂贵的 compaction probe；
- phase 状态实时可见，不能因 stdout buffering 让人误以为卡死；
- 失败输出稳定、脱敏的 `FAILURE_CLASS`；
- 私有 thread、raw JSONL、完整 prompt/tool body 只保存在 `~/.uwa/...`；
- 不要求操作者在受控 ChatGPT 页面手工点击、切换 surface、清空输入框或关闭弹窗；
- 验收过程不改变 Git 工作树；
- 验收结束后 `RUNNING_COUNT=0`。

### R9. 长上下文与 compaction

当前 RC 继续使用已经验证过的长上下文配置，发布前不重新调参。

若后续真实证据证明参数本身有缺陷，必须先修改需求或技术设计，再改配置。

### R10. 错误可诊断性

至少区分：

- listener/service 不健康；
- browser/CDP 未连接；
- stale/错误 ChatGPT surface；
- Work surface；
- usage exhausted；
- rate limited；
- submission unknown；
- route mismatch；
- remote compaction failure；
- post-compaction recovery failure；
- request cleanup failure；
- dirty/stale repository。

公开日志/status 只输出必要的脱敏信息。

## 4. S4 发布准备需求

### R11. 文档状态统一

S3 关闭后，以下文档必须同步到真实状态：

```text
README.md
README.en.md
README.th.md
README.ja.md
README.ko.md
README.zh-CN.md
CONTRIBUTING.md
CHANGELOG.md
docs/README.md
docs/ARCHITECTURE.md
docs/DEVELOPMENT.md
docs/BROWSER_SETUP.md
docs/TESTING.md
docs/TROUBLESHOOTING.md
docs/ROADMAP.md
docs/KNOWN_LIMITATIONS.md
docs/RELEASE_PROCESS.md
SECURITY.md
NOTICE.md
```

不得继续描述过期 blocker。快速开始命令必须可从干净 clone 执行。

### R12. 版本与变更记录

以下内容必须一致：

```text
VERSION
CHANGELOG.md
README status
Release Notes
Git tag
```

首个 RC tag：

```text
v0.1.0-rc.1
```

### R13. Release candidate CI

最终 candidate commit 必须通过 standalone CI、broad non-live Codex regression、public repo safety、dependency audit、release metadata check 和 S3 live parity。

CI 与 live gate 必须针对同一 candidate commit。

### R14. 安全与隐私

Release tree 不得包含 cookies、token/API key、浏览器 profile、私人 prompt、tool/command body、私人 workspace 内容、private Responses state、raw conversation URL、raw thread/session ID、完整 wire trace 或 `~/.uwa` runtime 文件。tracked `config/` 只能包含可复用的公共默认值，不得携带机器自己的 remembered route group、tab exclusion 或 conversation state。

默认网络边界保持：

```text
bind = 127.0.0.1
remote exposure = off
CORS = off
unsafe Python = off
```

### R15. License / Provenance

RC 必须包含完整 AGPL-3.0 License，并保留 upstream/integration provenance。

NOTICE 保留 `leeguooooo/chatgpt-use` 和 `kev489/gpt-tool-use` 的工程参考致谢。

### R16. 安装与回退 smoke test

最终 candidate 至少完成一次干净 checkout smoke test：

```text
clone
install wrappers
codex-uwa
codex-uwa-status
basic Codex request
codex-official
codex-uwa
codex-uwa-stop
```

必须证明 wrapper 指向 standalone repo、official 配置可恢复、authentication 不被修改、listener owner 校验正常。

### R17. Merge / Tag / Release 顺序

固定顺序：

1. `standalone-dev` 完成 S3/S4；
2. 冻结 candidate commit；
3. 最终 candidate CI + live gate 全绿；
4. fast-forward `main` 到已验收 candidate；
5. 确认 `main` 与 candidate 完全一致；
6. 等待同 SHA 的 main-branch CI 全绿；
7. 创建 `v0.1.0-rc.1` tag；
8. 从 tag 做 fresh checkout tagged-source smoke；
9. 创建 GitHub Release；
10. 发布 Release Notes、verified environment 和已知限制。

不得从未合并的开发分支直接创建正式 RC Release。

## 5. RC 已知限制

- 依赖 ChatGPT Web UI/DOM/行为，第三方页面变化可能造成兼容问题。
- 不增加或绕过 ChatGPT 账号消息、Work、模型、速率或其他平台配额。
- 首个 RC 的正式 live evidence 以当前 macOS + Codex Desktop/CLI + 本地受控浏览器为主。
- Windows/Linux 若没有同等级 live evidence，标记为未正式验证，不作为 RC 阻塞项。
- 本 RC 不强制引入新的 ChatGPT Web 内部 conversation-record API。

## 6. 明确不属于 v0.1.0-rc.1 的需求

- 新增其他 AI Web provider；
- 公网远程暴露；
- 多账号自动轮换规避配额；
- 自动切账号绕过 throttle；
- 新 GUI 管理后台；
- 大规模重构浏览器引擎；
- Windows/Linux 全平台正式认证；
- 新模型路由策略；
- 新长上下文阈值实验；
- 与发布无关的性能优化；
- `v0.1.0` stable release。

## 7. 发布前工作分解

### Gate A：需求冻结

输出：

```text
docs/RELEASE_REQUIREMENTS.md
```

完成标准：

```text
REQUIREMENTS_APPROVED=YES
```

### Gate B：技术设计冻结

输出：

```text
docs/RELEASE_TECHNICAL_DESIGN.md
```

技术设计必须逐项映射需求 ID，并说明模块、文件、测试、回滚和一次性 S3/S4 执行顺序。

完成标准：

```text
TECH_DESIGN_APPROVED=YES
```

### Gate C：按设计实现

只实现技术设计批准的改动。出现设计外问题时停止实现，回到需求/设计评审。

### Gate D：固定测试矩阵

固定顺序：

```text
compile/static
-> focused unit
-> broad non-live CI
-> local lifecycle/smoke
-> S3 live parity
-> S4 release checks
```

### Gate E：RC 冻结与发布

```text
candidate freeze
-> docs/version/changelog final sync
-> merge main
-> tag v0.1.0-rc.1
-> GitHub Release
```

## 8. 最终验收定义

只有同时满足以下条件才允许发布：

```text
S1=CLOSED
S2=CLOSED
S3=PASS_LIVE_CLOSED
S4=PASS
CI=GREEN
LIVE_GATE=GREEN
WORKTREE=CLEAN
SECURITY_CHECK=PASS
DEPENDENCY_AUDIT=PASS
PROVENANCE_CHECK=PASS
INSTALL_SMOKE=PASS
OFFICIAL_ROLLBACK=PASS
DOCS_SYNC=PASS
VERSION_SYNC=PASS
MAIN_CANDIDATE_MATCH=PASS
```

## 9. 需求变更控制

1. Bug 修复若不改变需求，只修改技术设计和实现记录。
2. 新增能力、改变发布范围或验收标准，先改需求文档。
3. 需求修改后重新评审，未评审前暂停相关实现。
4. 技术实现不得自行降低验收标准来让 gate 通过。
5. 外部平台限流、额度、页面异常必须被分类和报告，不能通过放宽正确性条件伪装成 PASS。

## 10. 当前状态解释

S1/S2 已作为抽取与解耦历史阶段关闭。S3/S4、Desktop、install smoke 和 CI 都是 candidate-bound release evidence，不能在需求文档里用一个长期不变的“当前 PASS/OPEN”快照代替真实结果。

允许 tag 的状态只能由当前 exact candidate 的证据共同证明：

```text
S1 = PASS / CLOSED
S2 = PASS / CLOSED
S3 = PASS_LIVE_CLOSED on current candidate
DESKTOP_E2E = PASS on current candidate
INSTALL_SMOKE = PASS on current candidate
S4 = PASS on current candidate
CI = GREEN on current candidate
main == candidate
main CI = GREEN
tagged-source smoke = PASS
```

任何代码或文档 commit 改变 candidate SHA 后，受影响的 candidate-bound evidence 必须重新生成。

S3 的 Web surface 准备要求已经正式固化为：唯一受控普通 Chat surface、空 composer、无 Work/usage/rate-limit/auth/challenge 阻断；该要求属于 R6/R8，不再作为“待解决缺口”描述。

## 11. 已批准的关键决策

- 首个 RC 范围只到 `v0.1.0-rc.1`，stable `v0.1.0` 另开后续需求。
- macOS 是首个 RC 的正式 live 验证平台，Windows/Linux 暂不作为阻塞项。
- Work surface 不允许承载 Codex Web Bridge 推理请求。
- usage/rate limit 只做检测、等待/失败和诊断，不做绕过。
- 发布前不再调整当前 77K/compaction 参数，除非有新证据证明参数本身有缺陷。
- 需求批准后先写技术设计，技术设计批准前不继续生产代码修改。
