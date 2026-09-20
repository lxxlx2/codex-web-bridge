# Codex Web Bridge v0.1.0-rc.1 发布前技术设计

**文档状态**：Approved v1.0  
**需求文档**：`docs/RELEASE_REQUIREMENTS.md` Approved v1.0  
**需求冻结提交**：`29609358de73c9ff3dbcd49da98172ce24ee66cd`  
**生产代码基线**：`de41c61347a71901b8116617e805de8e02aed372`  
**目标分支**：`standalone-dev`  
**目标版本**：`v0.1.0-rc.1`  
**审批状态**：`TECH_DESIGN_APPROVED=YES`

> 本文档只定义实现方案、文件边界、测试矩阵、回滚策略和发布顺序。批准后只允许实现本文档列出的内容；出现设计外问题时暂停实现并回到需求/设计评审。

---

## 1. 设计目标

本技术设计用于一次性收口剩余 S3/S4 工作，重点解决当前发布前链路中已经确认的四类问题：

1. ChatGPT Web target 存在，但 surface 可能是 Work/工作模式、旧会话或残留 composer，现有 S3 preflight 无法识别。
2. ChatGPT Web rate-limit 已有保护，但 surface readiness、usage exhaustion、Work quota、登录/挑战状态尚未形成统一状态模型。
3. S3 runner 的环境准备依赖外部临时 shell/CDP 操作，phase 输出在 pipe/tee 下可能缓冲，导致可重复性和可观测性不足。
4. S3 关闭后的 S4 文档、版本、安装回退、候选提交、CI、merge/tag/release 尚未形成机器可执行的固定 gate。

设计原则：

- fail closed；
- normal runtime 与 release acceptance 分离；
- 只读取完成判定所需的 Web UI 元数据，不读取对话正文、cookie、localStorage、账号 ID；
- S3 acceptance 可以重置其专用受控 ChatGPT target，normal runtime 不自动关闭用户 target；
- 不修改 77K/69.3K/73.15K/1024 长上下文参数；
- 不降低 required-tool、compaction lineage、empty completed output、tool side-effect 等现有正确性约束；
- cheap gate 全部通过后才执行昂贵 live gate；
- 每个实现 commit 映射到明确需求 ID；
- S3/S4 完成前不创建 RC tag。

---

## 2. 需求追踪矩阵

| 需求 | 设计组件 | 主要代码/文档 | 主要验收 |
|---|---|---|---|
| R1 Standalone 独立运行 | C7、C8 | lifecycle/provider/install/S4 gate | clean-checkout smoke |
| R2 本地工具权限边界 | 保持现有边界 | `codex_responses_v2.py`、executor | existing tool regression + S3 |
| R3 路由 | 保持现有 route audit | provider switch、route audit | config/session/wire 三证据 |
| R4 Same-thread | 保持现有 continuity | V2 affinity/compaction | S3 restart + post-compaction |
| R5 副作用安全 | 保持现有 hardening | required-tool/runtime hardening | existing regression |
| R6 Web surface 安全 | C1、C2、C4、C5 | surface inspector、prepare、S3 runner | surface unit + S3 preflight |
| R7 限流 | C3 | rate-limit guard | unit + lifecycle regression |
| R8 S3 | C5、C6 | S3 runner | complete live runner |
| R9 长上下文冻结 | 保护项 | provider/compaction config 不改 | config regression |
| R10 可诊断性 | C1、C4、C5 | surface snapshot、health、failure classes | unit + sanitized status |
| R11 文档同步 | C8 | README/CHANGELOG/SECURITY/NOTICE | S4 docs gate |
| R12 版本一致 | C8 | VERSION/CHANGELOG/release metadata | S4 version gate |
| R13 Candidate CI | C8、C9 | CI + candidate commit evidence | CI + candidate match |
| R14 安全隐私 | C4、C8 | health redaction/public safety | safety gate |
| R15 License/provenance | C8 | LICENSE/NOTICE | provenance gate |
| R16 安装回退 | C7、C8 | installer/lifecycle/provider | clean-checkout smoke |
| R17 Merge/tag/release | C9 | release process | final release checklist |

---

## 3. 当前架构与缺口

### 3.1 当前可复用能力

当前代码已经具备以下能力，本次设计直接复用，不重写：

- `app/services/chatgpt_web_prepare.py`
  - 能识别 `/c/...` 旧对话；
  - 能安全点击 New Chat；
  - 能确认 prompt editor 是否存在。
- `app/services/chatgpt_web_mode.py`
  - 能找到受控 `chatgpt.com` tab；
  - strict 模式下能拒绝多个 ChatGPT tab；
  - 能验证 GPT-5.6 Sol / reasoning / Temporary Chat 控件。
- `app/services/codex_web_policy.py`
  - fresh conversation 路径会先 prepare，再验证 web mode。
- `app/services/chatgpt_web_rate_limit_guard.py`
  - 已检测中英文 rate-limit modal；
  - 已持久化 20s/45s/90s cooldown；
  - 已阻止 ambiguous send 自动重发；
  - 已将 rate-limit 和 submission-unknown 变成 terminal workflow error。
- `app/services/request_manager.py`
  - 已有 QUEUED/RUNNING/COMPLETED/CANCELLED/FAILED 状态；
  - `/health` 已能提供 `running_count`。
- `tools/standalone_s3_live_acceptance.py`
  - repo preflight；
  - route 配置；
  - listener ownership/restart；
  - local safety/dependency/unit gates；
  - restart continuity；
  - native/Remote V2 compaction；
  - post-compaction recovery；
  - route audit；
  - final repo cleanliness。
- `tools/codex_uwa_lifecycle.py`
  - listener ownership fail-closed；
  - restart PID replacement；
  - stop 后端口清空证明。
- `tools/codex_provider_switch.py`
  - `codex-uwa` / `codex-official` 所需 provider 配置与 restore state；
  - authentication 不修改。

### 3.2 已确认缺口

当前 `fresh ChatGPT page` 判定只覆盖 pathname 和 prompt editor，不能区分：

```text
普通聊天
Work/工作
旧 project/work 会话
composer 残留
Work quota exhausted
普通 usage exhausted
rate limit
登录失效
challenge/interstitial
```

当前 `/health` 的 `service=healthy` 只表示 browser transport 可连接。这一语义是正确的，不能为了 surface 问题改成 unhealthy。需要额外增加独立的 surface readiness 信息。

当前 S3 runner 没有把“受控 browser target 准备”纳入自身，因此外部命令负责 close/create target，容易造成验收脚本与真实环境不一致。

当前 S3 phase 使用普通 `print()`，被 `tee`/pipe 捕获时可能出现 stdout buffering，操作者无法及时判断阶段。

---

## 4. 总体架构

新增一层统一的 ChatGPT Web Surface State：

```text
                    +-----------------------------+
                    | chatgpt_web_surface.py      |
                    | passive inspect/classify    |
                    +--------------+--------------+
                                   |
              +--------------------+--------------------+
              |                                         |
              v                                         v
+----------------------------+             +-----------------------------+
| normal runtime             |             | S3 acceptance               |
| chatgpt_web_prepare        |             | standalone_s3 runner        |
| codex_web_policy           |             | acceptance target reset     |
| send-time blocker guard    |             | safe surface normalization  |
+-------------+--------------+             +---------------+-------------+
              |                                            |
              v                                            v
+----------------------------+             +-----------------------------+
| Browser workflow           |             | expensive S3 probes         |
| no blind resend            |             | only after READY            |
+----------------------------+             +-----------------------------+
```

核心状态机：

```text
UNKNOWN
  |
  v
INSPECTING
  |
  +--> AUTH_REQUIRED ----------------> BLOCKED
  +--> CHALLENGE --------------------> BLOCKED
  +--> RATE_LIMITED -----------------> BLOCKED
  +--> USAGE_EXHAUSTED --------------> BLOCKED
  +--> WORK_QUOTA_EXHAUSTED ---------> BLOCKED
  +--> WORK_SURFACE
  |       |
  |       +-- acceptance only: SWITCH_CHAT_ONCE
  |               |
  |               +--> CHAT_SURFACE
  |               +--> BLOCKED
  |
  +--> CHAT_SURFACE
          |
          +--> existing conversation + fresh-flow
          |       |
          |       +--> NEW_CHAT_ONCE
          |
          +--> PRE_FILL composer non-empty --> BLOCKED
          |
          +--> CHAT_READY
```

normal runtime 不执行 acceptance target reset。S3 runner 才拥有“关闭并重建受控 target”的权限。

---

## 5. C1：统一 ChatGPT Web Surface Inspector

### 5.1 新文件

新增：

```text
app/services/chatgpt_web_surface.py
tests/test_chatgpt_web_surface.py
```

### 5.2 SurfaceSnapshot

内部使用 dataclass 或稳定 dict，字段只包含脱敏状态：

```text
target_count
host_ok
pathname_class
surface_kind
prompt_present
composer_chars
composer_empty
send_control_present
work_quota_exhausted
usage_exhausted
rate_limited
auth_required
challenge_present
surface_ready
blocking_reason
```

其中：

```text
pathname_class = root | conversation | other
surface_kind = chat | work | unknown
blocking_reason =
  none
  target_missing
  target_ambiguous
  work_surface
  composer_not_empty
  work_quota_exhausted
  usage_exhausted
  rate_limited
  auth_required
  challenge
  prompt_missing
  send_missing
  unknown_surface
```

禁止返回：

- conversation title；
- composer 正文；
- prompt 内容；
- cookie；
- localStorage；
- account ID；
- raw DOM HTML；
- raw URL conversation ID。

`/c/<id>` 只能归类为 `pathname_class=conversation`。

### 5.3 DOM 检测约束

Surface Inspector 的 JS 只允许：

- 读取当前 host/pathname 并立即归类；
- 检查 prompt/send 控件是否存在；
- 检查 composer 规范化字符数；
- 检查 exact/near-exact Chat/Work mode 控件的 selected/active 状态；
- 在 visible dialog/alert/status/banner/page chrome 范围内匹配明确的限流/额度/登录/challenge UI 模式。

禁止为了判断 blocker 对整个 conversation message tree 做全文采集。

composer 只返回字符数量。字符计数时去掉纯 whitespace 和零宽字符。

### 5.4 Surface kind 判定优先级

优先级固定：

```text
auth/challenge
> explicit Work quota / usage blocker
> selected Chat/Work mode control
> ordinary chat composer + recognized page chrome
> unknown
```

若证据冲突，例如同时检测到 selected Chat 和 selected Work，返回 `unknown` 并 fail closed。

---

## 6. C2：Fresh Composer / Pre-fill 准备

### 6.1 修改文件

```text
app/services/chatgpt_web_prepare.py
app/services/codex_web_policy.py
tests/test_chatgpt_web_prepare.py
tests/test_codex_web_policy.py
```

### 6.2 prepare 的职责

`prepare_chatgpt_fresh_composer()` 改为使用统一 Surface Inspector，并只用于“fresh-flow”。

顺序：

```text
find unique target
-> passive inspect
-> reject auth/challenge/quota/rate blocker
-> require chat surface
-> if /c/... then safe New Chat once
-> re-inspect
-> require prompt present
-> require composer empty
-> return sanitized preparation summary
```

normal runtime 如果发现 Work surface：

```text
raise ChatGPTWebModeError("chatgpt_web_work_surface")
```

normal runtime 不自动关闭 target，不自动清除 composer，不自动删除用户输入。

### 6.3 Acceptance 与 runtime 的差异

S3 acceptance 有额外权限，可以在任何模型请求发送前：

```text
reset acceptance-owned target
-> if SPA lands on Work:
     click exact Chat control once
-> if old conversation:
     click New Chat once
-> verify empty composer
```

normal runtime 不拥有 target reset 权限。

### 6.4 affinity 保持

`previous_response_id` 有有效 Web affinity 时：

- 不调用 fresh New Chat；
- 不清空对话；
- 不破坏 `/c/...` binding；
- 发送前仍必须执行 passive blocker guard；
- 若当前 surface 变成 Work/usage/rate/auth/challenge，直接 fail closed。

因此 C2 只管理 fresh-flow，C3 管理所有实际 send。

---

## 7. C3：所有 browser send 的 Surface Blocker Guard

### 7.1 修改文件

```text
app/services/chatgpt_web_rate_limit_guard.py
tests/test_chatgpt_web_rate_limit_guard.py
tests/test_chatgpt_web_rate_limit_workflow_terminal.py
```

文件名暂时保留，避免不必要的大规模 rename。内部职责扩展为 ChatGPT browser send guard。

### 7.2 两个时点

#### Pre-fill

由 C2 完成，要求 composer 空。

#### Pre-send

由 send guard 完成。此时 composer 已经被 workflow 填入请求，所以不能再要求 composer 空。

Pre-send 只检查：

```text
surface_kind == chat
no work quota
no usage exhausted
no rate-limit modal
no auth blocker
no challenge
```

### 7.3 错误映射

稳定映射：

| 条件 | workflow error | HTTP-like status |
|---|---|---:|
| Work surface | `chatgpt_web_work_surface` | 409 |
| Work quota exhausted | `chatgpt_web_work_quota_exhausted` | 429 |
| 普通 usage exhausted | `chatgpt_web_usage_exhausted` | 429 |
| rate limited | `chatgpt_web_rate_limited` | 429 |
| auth required | `chatgpt_web_auth_required` | 503 |
| challenge | `chatgpt_web_challenge` | 503 |
| submission unknown | `chatgpt_send_submission_unknown` | 422 |

理由：

- 401 容易被 Codex 客户端误解为 Bridge/API authentication 失败，因此 ChatGPT Web 登录失效使用 503 + 明确 code；
- Work surface 是当前页面状态冲突，使用 409；
- quota/rate 使用 429；
- submission unknown 延续现有 422。

所有 terminal error 都走现有 `stream_terminal_error:` 路径。

### 7.4 rate-limit probe 重构

现有 rate-limit JS 拆成：

```text
inspect_rate_limit(dismiss=False)
acknowledge_rate_limit()
```

S3 preflight 使用 `dismiss=False`，只诊断，不自动吞掉证据。

normal runtime 的现有 cooldown 行为可继续使用 acknowledgement，但必须满足：

```text
detected -> record cooldown
-> no automatic resend
-> bounded terminal unwind
```

不改变 20/45/90 秒阶梯。

---

## 8. C4：Health / Status 可诊断性

### 8.1 修改文件

```text
main.py
tests/test_standalone_entrypoint.py
```

### 8.2 `/health` 语义保持

继续：

```text
service=healthy
```

只代表：

```text
standalone service alive
+ browser transport connected
```

Work surface、usage exhausted、rate limit 不把 service 改成 degraded。

### 8.3 新增 sanitized readiness

`chatgpt_web` 扩展为：

```json
{
  "cooldown_active": false,
  "cooldown_remaining_seconds": 0,
  "hits": 0,
  "surface": {
    "surface_kind": "chat",
    "surface_ready": true,
    "pathname_class": "root",
    "prompt_present": true,
    "composer_empty": true,
    "send_control_present": true,
    "blocking_reason": "none"
  }
}
```

blocker 只返回布尔/枚举，不返回页面文字。

为避免健康检查频繁执行 DOM probe，可使用 1 秒左右的进程内短 TTL cache。该 cache 只缓存 sanitized snapshot。

如果 probe 自身异常：

```text
surface_ready=false
blocking_reason=surface_probe_failed
```

service 仍可保持 healthy。

---

## 9. C5：S3 Acceptance-owned Browser Target Preflight

### 9.1 修改文件

```text
tools/standalone_s3_live_acceptance.py
tests/test_codex_standalone_s3_runner.py
```

视实现复杂度允许新增：

```text
tools/chatgpt_surface_preflight.py
```

优先方案是共享 `chatgpt_web_surface.py`，runner 通过本地 browser/CDP 连接调用，不增加新的 HTTP 管理 API。

### 9.2 S3 对受控 target 的所有权

S3 运行时定义：

```text
受控 CDP 浏览器中的 ChatGPT target 是 acceptance disposable target
```

前提：

```text
Codex Desktop 已退出
running_count == 0
listener owner 已验证
```

满足前提后，S3 可以自动：

```text
close existing chatgpt.com page targets
create https://chatgpt.com/
```

这只适用于 S3 acceptance。

normal runtime 不执行此动作。

### 9.3 S3 Surface Preparation

新 target 创建后等待页面稳定，然后：

```text
inspect
-> Work?
     safe click exact Chat/聊天 control once
-> inspect
-> conversation?
     safe click New Chat once
-> inspect
-> require ordinary Chat surface
-> require empty composer
-> require no quota/rate/auth/challenge
```

如果安全控件无法唯一识别，直接 fail。

禁止：

- 通过坐标点击；
- 根据 conversation title 找控件；
- 清空未知 composer 文本；
- 自动发送测试 prompt 来判断 surface；
- 切换账号。

### 9.4 target reset 后 listener cache

为了避免 standalone listener 内的 browser/tab pool 持有 target reset 前的 stale reference：

```text
start/restart standalone listener
-> verify running_count=0
-> quiet Codex Desktop
-> reset acceptance target
-> prepare/verify surface
-> restart standalone listener once
-> health clean
-> passive re-check surface
-> enter local/live gates
```

该 restart 属于 environment bootstrap，不计入 restart-continuity proof。

真正 restart-continuity gate 仍按现有 S3 逻辑执行。

### 9.5 新增 S3 phase

增加：

```text
S3_PHASE=BROWSER_SURFACE_PREFLIGHT_PASS
```

最终 summary 可增加：

```text
S3_CHATGPT_SURFACE_PREFLIGHT=PASS
```

原 R8 要求的 marker 一个不删。

### 9.6 Failure classes

固定：

```text
chatgpt_target_missing
chatgpt_target_ambiguous
chatgpt_work_surface
chatgpt_composer_not_empty
chatgpt_work_quota_exhausted
chatgpt_usage_exhausted
chatgpt_web_rate_limited
chatgpt_auth_required
chatgpt_challenge
chatgpt_surface_unknown
chatgpt_surface_prepare_failed
```

这些 failure 必须发生在 compaction probe 前。

---

## 10. C6：S3 实时输出与证据

### 10.1 输出策略

runner 启动时：

```python
sys.stdout.reconfigure(line_buffering=True)
```

如果环境不支持则忽略。

所有 gate/phase 使用统一 helper：

```text
_emit("S3_PHASE=...", flush=True)
```

这样即使外部使用 `tee`，phase 也实时显示。

### 10.2 私有证据

继续保存在：

```text
~/.uwa/standalone-s3/<timestamp>/
```

新增：

```text
surface-preflight.json
```

只保存 sanitized snapshot 和 normalization actions：

```json
{
  "candidate_commit": "...",
  "target_reset": true,
  "actions": ["switch_to_chat", "new_chat"],
  "final_surface": {
    "surface_kind": "chat",
    "composer_empty": true,
    "blocking_reason": "none"
  }
}
```

不保存 conversation title、正文、composer text、raw DOM。

### 10.3 result.txt

成功证据增加：

```text
candidate_commit=<full sha>
STANDALONE_S3=PASS_LIVE_CLOSED
provider=uwa
model=chatgpt
effort=high
```

S4 用 `candidate_commit` 验证 live evidence 与候选提交一致。

---

## 11. C7：Standalone 安装 / 回退 smoke

### 11.1 保持现有 lifecycle 语义

`tools/codex_uwa_lifecycle.py` 的 listener ownership 规则保持不变。

`tools/codex_provider_switch.py` 的 provider/config/restore 规则保持不变。

不修改 authentication。

### 11.2 Clean checkout smoke

新增或扩展 versioned smoke runner，例如：

```text
tools/standalone_install_smoke.py
tests/test_standalone_install_smoke.py
```

在临时目录执行：

```text
git worktree/clean checkout
-> install wrappers into isolated temp bin
-> validate wrapper root
-> UWA switch
-> status
-> basic Responses request
-> official switch
-> verify restore state
-> UWA switch again
-> stop
```

对真实用户 `~/bin` / `~/.codex` 有副作用的部分不得在 CI 直接执行。

设计采用两层：

```text
CI: fake HOME + isolated config + mocked desktop/lifecycle
local RC smoke: dedicated temp HOME/config + real standalone listener/browser
```

正式 local smoke 必须记录 sanitized PASS marker。

---

## 12. C8：S4 Release Gate

### 12.1 新增

```text
tools/standalone_s4_release_gate.py
tests/test_standalone_s4_release_gate.py
```

### 12.2 S4 local gate 输出

计划输出：

```text
S4_DOCS_SYNC=PASS
S4_VERSION_SYNC=PASS
S4_SECURITY_CHECK=PASS
S4_PROVENANCE_CHECK=PASS
S4_INSTALL_SMOKE=PASS
S4_OFFICIAL_ROLLBACK=PASS
S4_S3_CANDIDATE_MATCH=PASS
STANDALONE_S4_LOCAL=PASS
```

### 12.3 Docs gate

检查：

```text
README.md
README.en.md
README.th.md
README.ja.md
README.ko.md
README.zh-CN.md
CHANGELOG.md
docs/RELEASE_PROCESS.md
SECURITY.md
NOTICE.md
docs/RELEASE_REQUIREMENTS.md
docs/RELEASE_TECHNICAL_DESIGN.md
```

至少验证：

- 不存在旧 post-compaction blocker 文案；
- S1/S2/S3/S4 状态一致；
- quick start 命令方向一致；
- `codex-uwa` 是 official -> UWA；
- `codex-official` 是 UWA -> official；
- NOTICE 仍有 upstream provenance 和两个公开可靠性参考项目；
- SECURITY 默认边界仍是 local-only。

### 12.4 Version gate

冻结 RC 时：

```text
VERSION = 0.1.0-rc.1
tag = v0.1.0-rc.1
```

检查 VERSION、CHANGELOG、README、Release Notes 模板的一致性。

### 12.5 S3 candidate match

读取最新成功的 private S3 result，并要求：

```text
result.candidate_commit == git HEAD
STANDALONE_S3=PASS_LIVE_CLOSED
```

private evidence 不提交到 Git。

---

## 13. C9：CI 与 Release Candidate 冻结

### 13.1 CI 修改

修改：

```text
.github/workflows/standalone-ci.yml
```

新增/保证：

```text
chatgpt surface unit tests
S3 runner non-live tests
S4 release metadata tests
public repo safety
dependency audit
broad Codex regression
```

GitHub hosted CI 不执行需要已登录 ChatGPT browser 的 live S3。

### 13.2 为什么最终需要两次计划内 full S3

为了同时满足：

```text
R11: S3 关闭后文档必须更新为真实状态
R13: 最终 candidate commit 必须有同 commit 的 live parity evidence
```

采用固定两次、非循环式 S3：

#### Live Gate A：S3 Closure

在所有生产代码实现、unit/CI/smoke 全绿后执行一次完整 S3：

```text
production implementation commit
-> full S3
-> STANDALONE_S3=PASS_LIVE_CLOSED
```

这一步正式关闭 S3。

#### S4 文档与版本提交

随后只允许修改：

```text
README*
CHANGELOG
VERSION
RELEASE_PROCESS
SECURITY/NOTICE（仅需要时）
release docs
```

禁止继续修改 production runtime。

#### Live Gate B：Frozen Candidate Confirmation

冻结 candidate commit 后，再执行一次完整 S3：

```text
candidate commit
-> full S3
-> candidate_commit == HEAD
-> all markers PASS
```

第二次的目的只有“candidate commit 一致性证明”，不再作为调试循环。

如果 Gate B 发现 production bug，candidate freeze 作废，回到设计/实现阶段。

如果只是外部 quota/rate-limit，保持 candidate 不变，等待外部条件恢复后重试 Gate B。

### 13.3 最终 CI

Frozen candidate push 后：

```text
GitHub CI all green
+ local S3 candidate-match PASS
+ S4 local gate PASS
```

才允许 merge `main`。

---

## 14. 文件级变更清单

### 新增文件

```text
app/services/chatgpt_web_surface.py
tests/test_chatgpt_web_surface.py
tools/standalone_install_smoke.py
tests/test_standalone_install_smoke.py
tools/standalone_s4_release_gate.py
tests/test_standalone_s4_release_gate.py
docs/RELEASE_TECHNICAL_DESIGN.md
```

### 修改生产/工具文件

```text
app/services/chatgpt_web_prepare.py
app/services/chatgpt_web_rate_limit_guard.py
app/services/codex_web_policy.py
main.py
tools/standalone_s3_live_acceptance.py
.github/workflows/standalone-ci.yml
```

`app/api/codex_responses_v2.py` 默认不修改。只有实现时证明 affinity reuse 无法通过 shared pre-send blocker guard 覆盖，才允许先回到技术设计评审再追加修改。

### 修改测试文件

```text
tests/test_chatgpt_web_prepare.py
tests/test_chatgpt_web_rate_limit_guard.py
tests/test_chatgpt_web_rate_limit_workflow_terminal.py
tests/test_codex_web_policy.py
tests/test_codex_standalone_s3_runner.py
tests/test_standalone_entrypoint.py
```

### S3 关闭后的 S4 文档修改

```text
README.md
README.en.md
README.th.md
README.ja.md
README.ko.md
README.zh-CN.md
CHANGELOG.md
VERSION
docs/RELEASE_PROCESS.md
SECURITY.md          # 仅需要同步 release disclosure/status 时
NOTICE.md            # provenance/acknowledgement 保持，不无谓改写
```

---

## 15. 明确禁止修改的区域

本 RC 剩余工作中默认禁止修改：

```text
77K model_context_window
69.3K auto-compact threshold
73.15K hard boundary
1024 remote summary limit
compaction lineage identity
required-tool generic satisfaction semantics
generic completed-empty-output guard
provider=uwa/model=chatgpt/high
body_after_prefix scope
listener ownership fail-closed rule
authentication behavior
```

如果实现中发现必须修改任一项，立即停止，并先修改需求/技术设计。

---

## 16. 测试设计

### T1 Surface classification unit

覆盖：

```text
chat root ready
chat /c conversation
work selected
conflicting chat/work evidence
work quota exhausted
ordinary usage exhausted
rate-limit modal
auth required
challenge
prompt missing
send missing
empty composer
dirty composer
multiple targets
```

只断言枚举和布尔值，不保存页面正文。

### T2 Fresh composer

覆盖：

```text
existing /c -> New Chat once
fresh root untouched
Work runtime -> fail closed
quota -> fail before new chat
dirty composer -> fail
safe control missing -> fail
```

### T3 Send blocker

覆盖：

```text
normal chat -> send allowed
work -> terminal 409
usage/work quota -> terminal 429
rate -> terminal 429
auth/challenge -> terminal 503
ambiguous send -> terminal 422
non-chatgpt route -> existing behavior
```

### T4 Health

覆盖：

```text
browser connected + work surface:
  service=healthy
  surface_ready=false

browser disconnected:
  service=degraded

surface probe exception:
  service semantics unchanged
  surface_ready=false
```

### T5 S3 non-live runner

覆盖：

```text
repo preflight fail -> no browser/live probe
running_count > 0 -> no target reset
target ambiguous -> no compaction
Work auto-normalize success -> continue
Work switch failure -> fail
dirty composer -> fail
usage/rate -> fail
surface ready -> local/live phases continue
candidate SHA written to private result
phase emit flushes
```

### T6 Existing Codex regression

继续执行：

```text
required tool
continuation
restart fallback
stream cancellation
remote compaction
post-compaction recovery
route audit
provider switch
lifecycle
security
```

### T7 S4 gate unit

覆盖：

```text
missing docs
stale blocker text
version mismatch
missing NOTICE acknowledgement
missing LICENSE
S3 evidence commit mismatch
S3 evidence marker missing
clean candidate success
```

---

## 17. 固定执行矩阵

实现批准后，所有改动完成时只按以下顺序运行。

### Stage 1：Cheap static

```text
py_compile
git diff --check
public_repo_safety_check
standalone_dependency_audit
```

任何失败先修，不跑后续。

### Stage 2：Focused unit

```text
chatgpt_web_surface
chatgpt_web_prepare
rate_limit_guard
web_policy
standalone_entrypoint
standalone_s3_runner
standalone_s4_release_gate
```

### Stage 3：Broad non-live

GitHub Standalone CI：

```text
scaffold
runtime-import
codex-regression
release-metadata
```

### Stage 4：Local lifecycle/smoke

```text
listener ownership
provider switch
official restore
clean checkout install
basic request
stop/restart
```

### Stage 5：Live Gate A

完整 S3 closure。

### Stage 6：S4 docs/version

仅文档和 release metadata。

### Stage 7：Frozen candidate

```text
CI green
Live Gate B
S4 local gate
candidate commit match
```

### Stage 8：merge/tag/release

```text
merge standalone-dev -> main
verify main commit
tag v0.1.0-rc.1
GitHub Release
```

---

## 18. Commit 计划

批准后按以下逻辑提交，允许实现过程中把同一逻辑拆成更小 commit，但不得跨需求混杂：

```text
Commit A
R6/R10
Add ChatGPT surface state model and passive diagnostics

Commit B
R6/R7/R10
Integrate fresh-composer and send-time blocker guards

Commit C
R6/R8
Make S3 own and verify its browser target; add realtime phases

Commit D
R1/R16
Add clean-checkout install/rollback smoke

Commit E
R11-R17
Add S4 release gate and CI metadata checks
```

S3 closure 后：

```text
Commit F
R11/R12/R15
Synchronize release docs, VERSION and changelog for rc.1
```

Commit F 后 production runtime 必须冻结。

---

## 19. 回滚策略

### Surface inspector / prepare

可整体回滚 Commit A/B。不会修改 persisted Responses state 或 Codex config schema。

### S3 browser target ownership

只影响 acceptance runner。回滚 Commit C 可恢复旧 runner，不影响 normal runtime。

### S4 tooling

只影响 release validation。可回滚 D/E，不触碰 runtime protocol。

### Provider/lifecycle

本设计不修改其核心行为，因此不存在新的 config migration。

### Runtime state

新 surface inspector 不新增持久化账号状态。

继续只使用现有：

```text
~/.uwa/chatgpt-rate-limit.json
~/.uwa/codex-provider-restore.json
~/.uwa/standalone-s3/...
```

---

## 20. 安全与隐私评审

Surface Inspector 必须通过以下检查：

```text
NO conversation text returned
NO composer text returned
NO cookies
NO localStorage
NO account ID
NO raw DOM
NO raw conversation URL ID
NO private prompt in logs
```

S3 target reset 只在：

```text
macOS release acceptance
Codex Desktop quiet
running_count=0
controlled CDP browser
```

条件同时满足时执行。

所有 private live evidence 权限保持 0600/0700。

---

## 21. 操作者体验

批准并实现后，最终 S3 不再需要用户复制多段临时 CDP shell。

目标命令收敛为：

```bash
cd ~/codex-web-bridge
git switch standalone-dev
git pull --ff-only
caffeinate -i .venv/bin/python tools/standalone_s3_live_acceptance.py
```

runner 自己完成：

```text
repo preflight
route setup
listener validation
Codex Desktop quiet
acceptance target reset
surface normalization
surface readiness
local gates
restart continuity
compaction
post-compaction recovery
route audit
cleanup
final result
```

如果失败，终端只需提供：

```text
STANDALONE_S3=FAIL
FAILURE_CLASS=<stable class>
PRIVATE_EVIDENCE_RECORDED=YES
```

无需用户打开 raw JSONL。

---

## 22. S4 / 发布操作体验

S3 closure 后：

```bash
.venv/bin/python tools/standalone_s4_release_gate.py
```

最终候选冻结后只允许：

```text
GitHub CI
Live Gate B
S4 gate
merge
tag
release
```

禁止在 candidate freeze 后顺手修改 production 代码。

---

## 23. 评审决策

### D1
S3 acceptance 对受控 ChatGPT target 拥有 disposable ownership，可以在 `RUNNING_COUNT=0` 且 Codex Desktop quiet 后自动 close/create。

**批准。**

### D2
S3 新 target 如果恢复到 Work surface，允许只点击一次经过精确识别的 `Chat/聊天` mode control，不发送 prompt；无法验证则 fail。

**批准。**

### D3
normal runtime 遇到 Work surface直接 fail closed，不自动关闭 target、不自动清 composer。

**批准。**

### D4
`/health` 增加 passive sanitized surface snapshot，但 `service=healthy` 仍只表示 service/browser transport healthy。

**批准。**

### D5
S3 runner 自身负责 line-buffered/flush phase 输出，不依赖用户加 `python -u`。

**批准。**

### D6
为了同时满足“文档真实”和“最终 candidate 同 commit live evidence”，发布前计划内执行两次 full S3：
- Gate A 关闭 S3；
- Gate B 验证 frozen RC candidate。

**批准。**

### D7
normal runtime 和 S3 都不绕过 Work/usage/rate quota，不切账号、不做 quota evasion。

**已由需求批准。**

### D8
当前长上下文和 compaction 参数冻结。

**已由需求批准。**

### D9
Windows/Linux 不作为 rc.1 release blocker，只标记为未完成同等级 live 验证。

**已由需求批准。**

---

## 24. 技术设计批准状态

本文档已批准并作为 Gate C 实现基线同步到：

```text
docs/RELEASE_TECHNICAL_DESIGN.md
```

批准状态：

```text
文档状态：Approved v1.0
TECH_DESIGN_APPROVED=YES
```

从该提交开始允许进入 Gate C 实现。

实现阶段仍需遵守：

```text
NO_DESIGN_DRIFT_WITHOUT_REVIEW=YES
NO_UNPLANNED_PRODUCTION_CHANGE=YES
```


---

## 25. Pre-tag onboarding and repository-hygiene addendum

A final pre-tag audit found three release-readiness issues outside the production inference path:

1. contributor onboarding did not provide a durable code map, development guide, test map, or troubleshooting index;
2. several historical S3/S4 documents still presented old gate state as if it were current;
3. tracked `config/browser_config.json` contained machine-specific remembered conversation/route state that conflicted with R14.

Approved implementation scope:

```text
production inference semantics: unchanged
README section structure: unchanged
developer documentation: add durable entrypoint/code-map/test/troubleshooting/roadmap docs
tracked browser defaults: remove machine-specific conversation/route state
public safety scanner: reject raw AI conversation URLs
S4 gate: verify new docs, reject stale release snapshots and tracked browser state
```

The tracked browser config keeps reusable runtime defaults but resets:

```text
tab_pool.excluded_urls = []
tab_pool.route_groups = []
tab_pool.auto_remember_url_presets = false
```

This prevents public source from carrying remembered machine/session state. It does not change Codex/ChatGPT routing semantics.

New durable documentation:

```text
CONTRIBUTING.md
docs/README.md
docs/ARCHITECTURE.md
docs/DEVELOPMENT.md
docs/TESTING.md
docs/TROUBLESHOOTING.md
docs/ROADMAP.md
requirements-dev.txt
.github/pull_request_template.md
```

Because these changes alter the candidate commit, all exact-candidate release evidence required by the release policy must be regenerated before tagging.
