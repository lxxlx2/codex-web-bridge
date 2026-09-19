# Standalone S3 Live Progress Log

This branch records live S3 acceptance progress without moving the active
`standalone-dev` release-candidate SHA. Candidate-bound release evidence remains
valid only for the exact candidate commit named in each entry.

## 2026-09-19 candidate 2b4deda4b1cce012a60ddc3c2eaa9ddd25376f73

Local validation:

```text
targeted: 75 passed in 0.51s
full suite: 495 passed, 22 warnings in 15.03s
```

Live S3 reached:

```text
S3_PHASE=RELEASE_PREFLIGHT_PASS
S3_PHASE=ACCEPTANCE_TARGET_RESET
S3_PHASE=BROWSER_SURFACE_PREFLIGHT_PASS
S3_CHATGPT_SURFACE_PREFLIGHT=PASS
S3_PHASE=REPO_PREFLIGHT_PASS
S3_PHASE=UWA_ROUTE_CONFIGURED
S3_PHASE=STANDALONE_LISTENER_READY
S3_PHASE=LOCAL_GATES_PASS
S3_PHASE=RESTART_CONTINUITY_PASS
```

This closes the previous restart-resume readback blocker on the exact candidate.
The specialized repair for the false claim that the current turn had no callable
client `exec_command` was exercised successfully by the live restart continuity
gate.

Current blocker:

```text
STANDALONE_S3=FAIL
FAILURE_CLASS=remote_compaction_probe
FAILURE_DETAIL=rc=1
```

Sanitized remote-compaction probe evidence:

```text
CONTEXT_WINDOW=77000
AUTO_COMPACT_LIMIT=69300
HARD_CONTEXT_LIMIT=73150
AUTO_COMPACT_SCOPE=body_after_prefix
TRIGGER_TARGET_LIMIT=73150
COARSE_BYTES=46000
FINE_BYTES=2048
SEED_REPLY_EXACT=YES
SEED_TOOL_EFFECTS=0
PRIVATE_THREAD_CAPTURED=YES
RUN_FAIL coarse_turn_failed round=1 rc=1
```

The failure occurs after a successful large-context seed and before the first
coarse filler turn completes. The next diagnostic step is to inspect the private
`trigger-probe-01-coarse.jsonl` trace and matching UWA/browser log metadata to
identify the direct Codex/browser failure behind the nonzero return code. Do not
rerun the full S3 stress probe until that direct failure is classified.

A prior 2026-09-19 live incident also failed on the first coarse turn because the
ChatGPT composer was filled before an older generation had become idle. That
incident led to the pre-fill idle guard and extended S3 pre-fill timeout. The
current failure must be compared against its private trace before deciding
whether this is the same lifecycle class or a new failure.


### Direct failure classification

The private coarse-turn trace confirms the direct failure:

```text
stream disconnected before completion: send_blocked_by_preexisting_generation
turn.failed
```

The matching UWA log shows the first coarse request entered the ChatGPT
composer pre-fill idle guard at 21:24:17, detected an existing generation/stop
state, waited the full S3 override of 300 seconds, and failed at 21:29:17 before
mutating the input box:

```text
[SEND] 发送前检测到页面仍处于旧生成/停止态，等待其结束后再提交本次消息 (timeout=300.0s)
[SEND] 等待旧生成态结束超时，本次发送动作尚未执行
send_blocked_by_preexisting_generation
```

This proves the newer pre-fill ordering fix is working as intended: the coarse
prompt was not stranded in the composer. The remaining blocker is that the
previous seed turn can leave the ChatGPT surface in a generation/stop state for
more than five minutes even after the visible exact reply
`LARGE_CONTEXT_READY` has already appeared.

The next implementation investigation should focus on terminal-state
reconciliation after a Web response becomes stable/exact. The bridge must not
start a new composer mutation while the old generation state remains live, but
the S3 path needs a safe way to distinguish a genuinely still-running response
from a stale UI generation state after the expected response is already stable.
No full S3 rerun should be performed until this lifecycle condition is handled
or a focused reproduction proves the state clears on its own.


### Source-level diagnosis

Inspection of `app/core/stream_monitor.py` found a matching completion hazard in
the text DOM monitor. When `ctx.content_ever_changed` is true, the ordinary
stable-text completion paths can break on stable-count/silence or fallback
silence without requiring `not still_generating`. The code only uses
`not still_generating` to tighten thresholds; it does not gate those normal
text exits.

That allows one browser-backed Codex turn to return a stable visible final text
while ChatGPT still exposes an active stop/generating state. The following turn
then correctly hits the pre-fill guard and fails after its bounded wait. This
matches the current live sequence exactly.

The next change should close that lifecycle gap with regression coverage. At a
minimum, ordinary text completion must not report the turn terminal while the
same active-turn generation indicator is still live. Any stale-generation
recovery/interrupt behavior must be separately bounded and proven safe, rather
than solved by simply extending the next-turn pre-fill timeout.
