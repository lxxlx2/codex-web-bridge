# Codex Web Bridge v0.1.0-rc.1 发布前测试方案

**文档状态**：Approved v1.0  
**需求基线**：`docs/RELEASE_REQUIREMENTS.md` Approved v1.0  
**技术设计基线**：`docs/RELEASE_TECHNICAL_DESIGN.md` Approved v1.0  
**技术设计提交**：`c0819d22a9a28e34414457cd8938f8c44e58199f`  
**目标分支**：`standalone-dev`  
**目标版本**：`v0.1.0-rc.1`  
**审批状态**：`TEST_PLAN_APPROVED=YES`

> 本文档是 RC 发布前的正式测试方案。发布前测试仅以 macOS 为正式 CI / non-live compatibility 环境；Linux CI 暂不纳入 `v0.1.0-rc.1` 范围。所有实现和验收必须按本文档固定 Gate 执行。

---

## 1. 评审结论

当前仓库已有较强的单元/回归基础，但**现有测试方案不足以直接作为 v0.1.0-rc.1 的完整发布前测试方案**。

已经具备并可直接复用的部分：

- standalone import / entrypoint 边界；
- Codex Responses、required-tool、continuation、route audit；
- Remote V2 compaction、compaction lineage、post-compaction recovery 相关回归；
- provider switch / restore state；
- listener ownership / restart fail-closed；
- ChatGPT Web rate-limit cooldown 与 ambiguous-submit 防重发；
- 默认安全配置、loopback、CORS、unsafe Python 等安全回归；
- broad non-live Codex regression；
- 当前 S3 live runner 的 restart continuity、native/remote compaction、post-compaction recovery、route/cleanup 证据链。

发布前仍缺少或不足的部分：

1. 没有统一的 ChatGPT surface 测试，无法覆盖 Chat/Work、Work quota、usage exhausted、auth/challenge、dirty composer。
2. 当前 S3 runner 的单元测试主要验证 helper/parser，尚未覆盖完整 preflight 控制流和 fail-fast 行为。
3. 当前 CI release metadata 只检查“文件存在”，没有检查 README/CHANGELOG/VERSION/tag/Release Notes 一致性。
4. 没有正式 S4 release gate。
5. 安装测试目前主要验证 wrapper 文本，没有完成 clean checkout + real lifecycle + official rollback smoke。
6. CI 需要统一到 RC 真实主环境 macOS + Python 3.14 的非 live 兼容性。
7. 没有最终 candidate commit 与 S3 live evidence 的 SHA 绑定测试。
8. 没有 merge/tag 前后的一致性与 tagged-source smoke。
9. rate-limit 虽有 unit/terminal 测试，但发布前还需要证明真实请求在限流后有界收尾并最终 `RUNNING_COUNT=0`。
10. `/health` 尚无“service healthy 但 Web surface blocked”的语义测试。

因此，本方案保留现有测试，补齐上述缺口，形成固定 Gate，不再采用临时命令和边测边改的方式。

---

## 2. 测试目标

RC 测试必须证明：

```text
代码正确
+ standalone 独立
+ 安装/切换/回退可靠
+ 本地工具权限边界正确
+ same-thread / restart / compaction 连续性正确
+ ChatGPT Web surface fail-closed
+ rate-limit 不重复发送且有界收尾
+ 安全/隐私符合公开发布要求
+ 文档/版本/候选提交一致
+ 最终发布 tag 指向已验收 candidate
```

测试不用于：

- 绕过 ChatGPT 配额；
- 试验新的长上下文参数；
- 认证 Windows/Linux；
- 测试其他 AI provider；
- 做与 rc.1 无关的性能优化。

---

## 3. 发布阻塞等级

### P0 Release Blocker

任何一个 P0 失败都禁止发布：

```text
public repo safety
dependency/import boundary
provider/model/effort route
required-tool real roundtrip
restart continuity
native compaction
Remote V2 compaction
post-compaction recovery
Web surface safety
rate-limit bounded unwind
request cleanup
clean checkout install
official rollback
candidate SHA match
version/docs/provenance consistency
final CI
final live gate
```

### P1 Required Regression

必须执行并通过，但失败通常先定位是否为测试环境：

```text
broad non-live Codex regression
health diagnostics
negative surface classification
listener ownership negative paths
config restore/idempotency
tag/source archive smoke
```

### P2 Informational

不阻塞 rc.1：

```text
Windows/Linux live parity
性能 benchmark
非主环境浏览器兼容性
长期压力测试
```

---

## 4. 测试环境

### E1：macOS CI

用途：

```text
compile/static
import boundary
focused unit/regression
broad non-live Codex regression
release metadata
security
dependency audit
provider/lifecycle non-live regression
installer/wrapper behavior
Python 3.14 compatibility
```

正式 CI 环境：

```text
macos-latest + Python 3.14
```

本 RC 不要求 Linux CI。现有 Linux workflow 在实现阶段应迁移为 macOS-only，或从 release-blocking workflow 中移除；不得把 Linux job 状态作为 rc.1 发布 gate。

GitHub CI 不登录 ChatGPT，不运行 live S3。

### E2：本地 RC 主验收环境

主 live evidence 环境：

```text
macOS
Python 3.14
Codex Desktop / CLI
standalone repo
loopback UWA :8199
controlled browser CDP :9222
已登录且具备目标模型能力的 ChatGPT Web
```

live gate 开始前要求：

```text
worktree clean
HEAD == origin/standalone-dev
Codex Desktop quiet
RUNNING_COUNT=0
ChatGPT target uniquely controlled
surface ready
```

### E3：Clean Checkout Smoke

使用独立 checkout/worktree + 临时 HOME/config，避免使用已有开发目录状态。

必须证明：

```text
不依赖 ~/universal-web-api
wrapper 指向 standalone checkout
provider restore state 正确
authentication 不被修改
listener ownership 正常
```

## 5. 测试数据与隐私规则

测试数据必须使用合成 marker/token，不使用真实私人项目内容。

公开输出禁止包含：

```text
raw thread/session ID
raw rollout path
conversation ID
私人 prompt
tool/command body
workspace 内容
cookie/token/API key
browser profile
raw DOM
完整 wire trace
~/.uwa 私有文件内容
```

允许公开：

```text
PASS/FAIL marker
failure class
计数
布尔状态
hash/脱敏 identity
candidate commit SHA
provider/model/effort
```

private live evidence 保存在：

```text
~/.uwa/standalone-s3/<timestamp>/
```

权限：

```text
directory 0700
private file 0600
```

---

## 6. Gate 0：Repo / Static / Safety

### G0-01 Repository preflight

验证：

```text
branch == standalone-dev
HEAD == origin/standalone-dev
worktree clean
runtime-generated config/commands.json 不进入 Git
```

### G0-02 Compile

至少覆盖：

```text
start.py
main.py
app/api/standalone_routes.py
app/api/codex_runtime.py
app/api/codex_responses_v2.py
app/services/codex_chatgpt_executor.py
app/services/chatgpt_web_surface.py
app/services/chatgpt_web_prepare.py
app/services/chatgpt_web_rate_limit_guard.py
app/services/codex_web_policy.py
tools/codex_provider_switch.py
tools/codex_uwa_lifecycle.py
tools/standalone_s3_live_acceptance.py
tools/standalone_install_smoke.py
tools/standalone_s4_release_gate.py
```

### G0-03 Static integrity

执行：

```text
git diff --check
public_repo_safety_check
standalone_dependency_audit --check
tracked browser_config has no machine-specific conversation URLs,
route groups, remembered tab exclusions, or auto-remember state
```

### G0-04 Security defaults

必须验证：

```text
bind=127.0.0.1
CORS=off
unsafe Python=off
auto update=off
remote exposure=off
```

### G0 Exit

全部 PASS 后才进入 focused unit。

---

## 7. Gate 1：Focused Unit / Component

### G1-01 ChatGPT Surface State

新增 `tests/test_chatgpt_web_surface.py`，至少覆盖：

```text
chat root ready
chat existing conversation
work selected
chat/work conflicting evidence
work quota exhausted
ordinary usage exhausted
rate-limit modal
auth required
challenge/interstitial
prompt missing
send missing
composer empty
composer dirty
target missing
multiple targets
surface probe failure
```

验证重点：

```text
surface_kind
surface_ready
blocking_reason
pathname_class
composer_chars only
```

禁止测试返回正文。

### G1-02 Fresh Composer

扩展 `tests/test_chatgpt_web_prepare.py`：

```text
existing /c -> safe New Chat once
fresh chat root -> untouched
Work runtime -> fail closed
usage/quota -> fail before navigation
dirty composer -> fail closed
safe control missing -> fail
new-chat navigation timeout -> fail
```

### G1-03 Send Guard

扩展 rate-limit/send tests：

```text
normal chat -> allow
Work -> terminal 409
Work quota -> terminal 429
usage exhausted -> terminal 429
rate limit -> terminal 429
auth/challenge -> terminal 503
ambiguous submit -> terminal 422
non-chatgpt route -> unchanged
```

必须验证 terminal error 不进入 workflow retry。

### G1-04 Health semantics

扩展 `tests/test_standalone_entrypoint.py`：

```text
browser connected + chat ready:
  service=healthy
  surface_ready=true

browser connected + Work/quota:
  service=healthy
  surface_ready=false

browser disconnected:
  service=degraded

surface probe exception:
  service transport semantics不变
  surface_ready=false
```

### G1-05 S3 Runner Control Flow

当前 `test_codex_standalone_s3_runner.py` 需要从 helper 测试扩展到流程测试：

```text
repo preflight fail -> no live/browser probe
running_count > 0 -> no target reset
multiple targets -> fail fast
Work -> switch Chat once
Work switch unavailable -> fail fast
dirty composer -> fail fast
usage/rate/auth/challenge -> fail fast
surface ready -> can enter live gate
phase output flush
candidate SHA recorded
failure output no private identifiers
```

### G1-06 Provider / Lifecycle

保留现有：

```text
provider restore
config idempotency
body_after_prefix override
foreign listener refusal
restart PID replacement
port empty proof
```

再补：

```text
wrapper root == current standalone checkout
official -> uwa -> official -> uwa repeated cycle
restore state absent/corrupt fail-closed
```

### G1-07 Release Gate Unit

新增 `tests/test_standalone_s4_release_gate.py`：

```text
missing docs
README status mismatch
VERSION mismatch
tag mismatch
CHANGELOG mismatch
missing LICENSE
NOTICE acknowledgement missing
SECURITY default mismatch
S3 evidence missing
S3 candidate SHA mismatch
dirty worktree
clean release candidate success
```

### G1 Exit

所有 focused unit 100% PASS。

---

## 8. Gate 2：Broad Non-live Regression

CI 必须继续运行现有 Codex 主回归：

```text
tests/test_codex*.py
tests/test_client_tool_policy*.py
tests/test_chatgpt_web_*.py
tests/test_install_codex_uwa_commands.py
tests/test_security_hardening.py
```

现有明确排除的 staged/live-only tests 保持排除，除非实现阶段确认已适合普通 CI。

必须重点覆盖：

```text
Responses contract
required tool
tool result continuation
same-thread identity fencing
session affinity
lost-affinity restart fallback
uncertain tool effect retry
stream cancellation
remote compaction V2
recursive compaction
post-compaction recovery logic
route audit
wire observability
provider switch
memory guard
lifecycle
security
```

### CI 补充

RC 前统一为 macOS-only：

```text
macOS Python 3.14 compile/import
macOS Python 3.14 focused + broad non-live regression
release-metadata job
```

现有 Ubuntu/Python 3.13 release-blocking job 不再作为 rc.1 必需项。

### G2 Exit

```text
all required CI jobs green
no skipped release-blocking test
```

---

## 9. Gate 3：Clean Checkout / Install / Rollback Smoke

新增 versioned smoke runner。

### G3-01 Clean checkout

从干净 candidate checkout 开始。

验证：

```text
no dependency on universal-web-api path
README quick-start commands valid
```

### G3-02 Install wrappers

执行并验证：

```text
install_codex_uwa_commands.py
codex-uwa
codex-uwa-status
codex-uwa-stop
codex-official
```

wrapper 必须绑定当前 standalone repo。

### G3-03 UWA switch

验证：

```text
model_provider=uwa
model=chatgpt
reasoning=high
body_after_prefix
restore state present
authentication unchanged
```

### G3-04 Listener

验证：

```text
8199 owned by standalone checkout
health PASS
restart replaces listener PID
foreign listener fails closed
```

### G3-05 Basic request

发起一个小型真实 Codex request：

```text
no compaction
no destructive tool
exact deterministic acknowledgement
```

验证：

```text
request reaches UWA
route correct
request terminates
RUNNING_COUNT=0
```

### G3-06 Official rollback

执行：

```text
codex-official
```

验证：

```text
UWA listener stopped
provider/model/effort pin removed
pre-UWA managed settings restored
authentication unchanged
desktop reopen behavior符合设计
```

### G3-07 Switch back

再次：

```text
codex-uwa
codex-uwa-status
codex-uwa-stop
```

证明切换流程可重复。

### G3 Exit

输出：

```text
INSTALL_SMOKE=PASS
OFFICIAL_ROLLBACK=PASS
```

---

## 10. Gate 4：Web Surface Real Preflight

这是 live S3 的前置 gate，不发送长上下文。

runner 自动完成：

```text
Codex Desktop quiet
RUNNING_COUNT=0
close acceptance-owned old ChatGPT targets
create fresh ChatGPT target
inspect surface
if Work -> exact Chat switch once
if conversation -> exact New Chat once
verify empty composer
verify no Work quota
verify no ordinary usage exhausted
verify no rate-limit
verify no auth/challenge
restart listener once to remove stale target cache
passive recheck
```

### 必须 fail-fast 的真实场景

如果当前真实 UI 出现：

```text
Work quota exhausted
usage exhausted
rate limit
login required
challenge
ambiguous target
dirty composer
unknown surface
```

则：

```text
不进入 compaction probe
不发送 S3 长上下文
输出稳定 FAILURE_CLASS
RUNNING_COUNT 最终回 0
```

---

## 11. Gate 5：S3 Live Gate A

实现完成后执行第一次完整 S3，用于正式关闭 S3。

必须同时出现原要求 marker：

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

新增 surface marker 可额外要求：

```text
S3_CHATGPT_SURFACE_PREFLIGHT=PASS
```

### S3 具体证明

#### G5-01 Real client tool

必须有真实 Codex client tool execution。

文本模拟失败。

#### G5-02 Restart continuity

同一 thread：

```text
turn 1
-> standalone listener restart
-> turn 2 resume
```

thread identity 必须匹配。

#### G5-03 Native auto-compaction

使用当前冻结配置触发 native compaction。

禁止为通过测试调整 77K/69.3K/73.15K。

#### G5-04 Remote V2 compaction

必须证明 remote compaction route/success。

#### G5-05 Post-compaction recovery

同一 thread 继续真实工具行为，并验证最终结果。

#### G5-06 Route

配置、session/rollout、wire 三类证据：

```text
uwa
chatgpt
high
```

全部一致。

#### G5-07 Cleanup

结束时：

```text
RUNNING_COUNT=0
worktree clean
```

### Rate-limit special acceptance

如果 live 期间遇到 429：

```text
不得自动重复发送
请求必须有界终止
request manager 必须收尾
该次 S3 FAIL
```

这是正确的 fail-closed，不算产品错误，除非出现 stuck/duplicate send/cleanup failure。

---

## 12. Gate 6：S4 Release Consistency

S3 Gate A 关闭后，仅允许 docs/version/release metadata 修改。

S4 gate 必须验证：

```text
README 多语言状态一致
README quick start 面向 main / Release，不要求普通用户切开发分支
CONTRIBUTING + docs/README/ARCHITECTURE/DEVELOPMENT/TESTING/TROUBLESHOOTING/ROADMAP 存在
历史 S3/S4 文档不再伪装成当前 release 状态
CHANGELOG 与版本一致
VERSION == 0.1.0-rc.1
planned tag == v0.1.0-rc.1
RELEASE_PROCESS 状态正确
SECURITY 默认边界正确
tracked browser config 不含 machine-specific conversation state
LICENSE 存在且完整
NOTICE provenance/acknowledgement 正确
public repo safety PASS
dependency audit PASS
install smoke PASS
official rollback PASS
```

输出：

```text
S4_DOCS_SYNC=PASS
S4_VERSION_SYNC=PASS
S4_SECURITY_CHECK=PASS
S4_PROVENANCE_CHECK=PASS
S4_INSTALL_SMOKE=PASS
S4_OFFICIAL_ROLLBACK=PASS
```

---

## 13. Gate 7：Frozen Candidate Confirmation

完成 docs/version 后冻结 candidate commit。

从此：

```text
production runtime 不再修改
candidate SHA 固定
```

### G7-01 Final CI

必须针对 frozen candidate SHA 全绿。

### G7-02 Live Gate B

对 frozen candidate 再执行一次完整 S3。

目的仅为证明：

```text
最终 candidate commit
==
最终 live evidence commit
```

private S3 result 必须包含：

```text
candidate_commit=<HEAD full SHA>
STANDALONE_S3=PASS_LIVE_CLOSED
```

### G7-03 S4 candidate match

S4 gate 验证：

```text
S3 evidence candidate_commit == git HEAD
```

输出：

```text
S4_S3_CANDIDATE_MATCH=PASS
STANDALONE_S4_LOCAL=PASS
```

### Gate B 重跑规则

如果失败原因是：

```text
rate limit
usage exhausted
Work quota
外部 ChatGPT 暂时不可用
```

candidate 不变，等待外部条件恢复后允许重跑 Gate B。

如果失败原因是：

```text
代码逻辑
route
tool
continuity
compaction
cleanup
security
installer
docs/version
```

candidate freeze 作废，回到实现/设计流程。

---

## 14. Gate 8：Merge / Tag / Release Verification

### G8-01 Merge

```text
standalone-dev -> main
```

验证：

```text
main commit == frozen candidate commit
```

若 merge commit 策略造成 SHA 改变，则必须证明 tree 相同，并按发布流程明确记录；优先使用能保持已验收 commit 身份的策略。

### G8-02 Tag

创建前验证：

```text
main clean
CI green
S3 candidate match
S4 PASS
```

创建：

```text
v0.1.0-rc.1
```

验证 tag 指向已批准 release commit。

### G8-03 Tagged source smoke

从 tag 做一次只读/轻量 smoke：

```text
fresh checkout tag
VERSION correct
README quick start files present
LICENSE/NOTICE/SECURITY present
public_repo_safety_check PASS
dependency audit PASS
```

如果 release process 最终包含生成 bundle，再追加：

```text
bundle built from tag
SHA-256 recorded
bundle contains no private runtime state
```

GitHub 自动 source ZIP/tar.gz 不需要重复构建。

---

## 15. 需求追踪与测试映射

| 需求 | Release-blocking 测试 |
|---|---|
| R1 | G0、G3 |
| R2 | G2 required-tool + G5 real client tool |
| R3 | G2 route audit + G5 route triple evidence |
| R4 | G2 continuation/affinity + G5 restart/compaction |
| R5 | G2 required-tool/uncertain side-effect |
| R6 | G1 surface + G4 real preflight |
| R7 | G1 send guard + G5 bounded live failure behavior |
| R8 | G4 + G5 |
| R9 | config regression + G5 frozen values |
| R10 | G1 health/failure class + G4/G5 sanitized evidence |
| R11 | G6 docs sync |
| R12 | G6 version sync + G8 tag |
| R13 | G2 CI + G7 candidate match |
| R14 | G0 security/safety + G6 |
| R15 | G6 provenance/license |
| R16 | G3 clean checkout/rollback |
| R17 | G7 + G8 |

任何 R1-R17 如果没有至少一个明确 release-blocking test，不允许发布。

---

## 16. CI 最终形态

最终 GitHub Actions 采用 macOS-only，至少包含：

```text
scaffold-static
runtime-import
codex-regression
release-metadata
```

所有 job 使用：

```text
runs-on: macos-latest
Python: 3.14
```

### scaffold-static

```text
compile
file presence
import boundary
entrypoint boundary
public repo safety
```

### runtime-import

```text
install runtime
import main
route boundary
dependency audit
focused standalone tests
```

### codex-regression

```text
broad non-live Codex tests
client-tool policy
ChatGPT Web tests
provider/lifecycle/security
```

### release-metadata

```text
requirements/design/test-plan presence
docs/version consistency
LICENSE/NOTICE/SECURITY
S4 gate unit
```

GitHub CI 不运行真实登录 ChatGPT Web 的 S3。

---

## 17. 精确重跑策略

禁止“失败后直接整套再跑”。

### Unit/CI failure

只修对应问题，先跑 focused，再 broad。

### G3 smoke failure

只重跑 clean checkout smoke，直到通过。

### G4 surface preflight failure

不跑 S3。

如果是外部 quota/rate，等待外部条件变化。

### G5 S3 product failure

读取 private evidence，只做窄诊断。

修复后：

```text
focused regression
-> broad regression
-> G3/G4
-> full S3
```

### G5 S3 external failure

代码不变时无需重新跑 broad CI。

环境恢复后从 G4 开始。

### Frozen candidate 失败

生产 bug：

```text
unfreeze candidate
-> implementation
-> all affected gates
-> new candidate
```

外部 ChatGPT 状态：

```text
candidate remains frozen
-> retry G4/G7 live gate only
```

---

## 18. 时间与挂起保护

所有外部/浏览器测试必须有 bounded timeout。

现有 S3 可继续使用：

```text
normal turn timeout = 600s
compaction timeout = 900s
cleanup timeout = bounded
```

要求：

- 已识别 rate-limit 后不得继续等待 generic 600s stuck watchdog；
- 每个 S3 phase 实时 flush；
- 任一 phase 超时都有稳定 failure class；
- timeout 后 request manager 最终进入 terminal state；
- runner 不留下 orphan running request。

不设“必须几分钟内完成”的性能 SLA，本 RC 只要求功能有界完成。

---

## 19. 测试证据

### CI 证据

GitHub Actions：

```text
candidate SHA
job status
test summary
```

### Local smoke

只输出 sanitized marker：

```text
INSTALL_SMOKE=PASS
OFFICIAL_ROLLBACK=PASS
```

### S3

private：

```text
~/.uwa/standalone-s3/<timestamp>/
```

public terminal：

```text
phase marker
PASS markers
failure class
candidate SHA
```

### S4

输出：

```text
S4_* markers
STANDALONE_S4_LOCAL=PASS
```

### Release record

Release Notes 记录：

```text
candidate commit
tag
verified primary environment
known limitations
candidate CI green
main CI green
S3 PASS
Desktop E2E PASS
install smoke PASS
S4 PASS
tagged-source smoke PASS
```

不上传 private S3 evidence。

---

## 20. 发布 Exit Criteria

只有同时满足以下条件才允许创建 `v0.1.0-rc.1`：

```text
REQUIREMENTS_APPROVED=YES
TECH_DESIGN_APPROVED=YES
TEST_PLAN_APPROVED=YES

S1=CLOSED
S2=CLOSED
S3=PASS_LIVE_CLOSED
S4=PASS

CI=GREEN
CI_MACOS_ONLY=GREEN
PUBLIC_REPO_SAFETY=PASS
DEPENDENCY_AUDIT=PASS
SECURITY_CHECK=PASS
PROVENANCE_CHECK=PASS
INSTALL_SMOKE=PASS
OFFICIAL_ROLLBACK=PASS

FINAL_CANDIDATE_SHA_MATCH=YES
LIVE_EVIDENCE_SHA_MATCH=YES
MAIN_RELEASE_TREE_MATCH=YES
WORKTREE=CLEAN
TAG=v0.1.0-rc.1
```

任一项缺失，不发布。

---

## 21. 实现前需要补齐的测试资产

批准本测试方案后，Gate C 实现阶段必须创建/扩展：

```text
NEW
tests/test_chatgpt_web_surface.py
tests/test_standalone_install_smoke.py
tests/test_standalone_s4_release_gate.py
tools/standalone_install_smoke.py
tools/standalone_s4_release_gate.py

EXPAND
tests/test_chatgpt_web_prepare.py
tests/test_chatgpt_web_rate_limit_guard.py
tests/test_chatgpt_web_rate_limit_workflow_terminal.py
tests/test_codex_web_policy.py
tests/test_codex_standalone_s3_runner.py
tests/test_standalone_entrypoint.py
.github/workflows/standalone-ci.yml
```

已有 compaction、route、required-tool、provider、lifecycle、安全测试原则上直接复用，除非实现改动触及对应模块。

---

## 22. 测试方案批准后的固定执行顺序

最终只允许按下面顺序收口：

```text
1. Gate 0  Repo/static/safety
2. Gate 1  Focused unit
3. Gate 2  Broad non-live CI
4. Gate 3  Clean checkout install/rollback smoke
5. Gate 4  Real Web surface preflight
6. Gate 5  S3 Live Gate A
7. Gate 6  S4 docs/version/release consistency
8. Freeze candidate
9. Gate 7  Final CI + S3 Live Gate B + candidate match
10. Gate 8 Merge main + tag verification + tagged-source smoke
11. GitHub Release
```

该顺序批准后固定。出现设计外问题时停止，不临时追加“顺手测试”替代方案。

---

## 23. 审批项

已批准：

```text
T-D1 当前测试基础可复用，但不足以直接发布，必须补齐本方案新增项。
T-D2 CI 统一为 macOS + Python 3.14；Linux CI 暂不进入 rc.1 发布范围。
T-D3 S3 surface preflight 是 full S3 的强制前置条件。
T-D4 clean checkout install/official rollback 是 RC 强制 smoke。
T-D5 最终 frozen candidate 必须再跑一次 full S3 绑定同一 SHA。
T-D6 tag 前必须验证 main release tree 与 frozen candidate 一致。
T-D7 tag 后执行轻量 tagged-source smoke。
T-D8 Windows/Linux live parity 不作为 rc.1 blocker。
```

本方案已批准并冻结：

```text
文档状态：Approved v1.0
TEST_PLAN_APPROVED=YES
```

同步路径：

```text
docs/RELEASE_TEST_PLAN.md
```
