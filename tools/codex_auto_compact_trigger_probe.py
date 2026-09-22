#!/usr/bin/env python3
"""P1.2 small-step probe for Codex pre-turn auto-compaction.

Codex 0.153.4 evaluates auto-compaction before the new user message is recorded.
A large fixed filler can therefore jump from below the threshold to an oversized
sampling request without giving the next turn a chance to observe an already
high previous context. This probe grows a fresh synthetic thread coarsely, then
switches to ~2 KiB filler near the 90% auto-compact threshold, and finally sends
one tiny trigger turn.

The current UWA provider is expected to select Codex's local compaction fallback.
The probe proves the trigger path by counting only bounded compact lifecycle
markers in the private Codex rollout. It never prints the thread id, rollout
path, prompts, response bodies, or tool payloads.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
import tomllib
from pathlib import Path
from typing import Any

import codex_large_context_acceptance as base
import codex_large_context_live as live


DEFAULT_COARSE_BYTES = 46_000
DEFAULT_FINE_BYTES = 2_048
DEFAULT_COARSE_GUARD_TOKENS = 8_000
DEFAULT_ARM_GUARD_TOKENS = 512
DEFAULT_TRANSITION_RESERVE_TOKENS = 256
DEFAULT_TRANSITION_MIN_BYTES = 1024
DEFAULT_MAX_COARSE_ROUNDS = 14
DEFAULT_MAX_FINE_ROUNDS = 12
DEFAULT_MAX_ARM_ROUNDS = 8
DEFAULT_TIMEOUT_SEC = 900
DEFAULT_PRE_SUBMIT_RETRY_DELAY_SEC = 5.0
PREEXISTING_GENERATION_MARKER = "send_blocked_by_preexisting_generation"
AUTO_COMPACT_PERCENT = 90
HARD_CONTEXT_PERCENT = 95
ARM_ACK_PREFIX = "AUTO_COMPACT_ARM_ACK"
TRIGGER_ACK = "AUTO_COMPACT_TRIGGER_OK"


def auto_compact_limit(context_window: int) -> int:
    return context_window * AUTO_COMPACT_PERCENT // 100


def hard_context_limit(context_window: int) -> int:
    return context_window * HARD_CONTEXT_PERCENT // 100



def configured_auto_compact_scope(
    config_path: Path | None = None,
) -> str:
    """Read the active Codex auto-compaction scope safely."""

    path = (
        config_path.expanduser()
        if config_path is not None
        else Path.home() / ".codex" / "config.toml"
    )

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return "total"

    scope = str(
        data.get("model_auto_compact_token_limit_scope") or "total"
    ).strip().lower()

    if scope not in {"total", "body_after_prefix"}:
        return "total"

    return scope


def trigger_target_limit(context_window: int, scope: str) -> int:
    """Choose a deterministic pre-turn compaction trigger target.

    Total scope can use the normal 90% auto-compaction threshold.

    BodyAfterPrefix subtracts a runtime prefill baseline and may also carry a
    fallback buffer that is not represented by the CLI cumulative usage
    snapshot. The full-context limit remains an independent Codex compaction
    trigger, so use that boundary for deterministic live acceptance.
    """

    if scope == "body_after_prefix":
        return hard_context_limit(context_window)

    return auto_compact_limit(context_window)


def cumulative_tokens(observation: base.ExecObservation) -> int | None:
    if not observation.input_tokens:
        return None
    input_tokens = observation.input_tokens[-1]
    output_tokens = observation.output_tokens[-1] if observation.output_tokens else 0
    return input_tokens + output_tokens


def active_response_tokens(previous_cumulative: int, current_cumulative: int) -> int:
    return current_cumulative - previous_cumulative


def build_trigger_prompt() -> str:
    prompt = (
        "P1.2 auto-compaction trigger turn. Do not call tools. Do not read files, logs, "
        "session history, memory stores, ~/.codex, or ~/.uwa. "
        f"Reply with exactly {TRIGGER_ACK} and nothing else."
    )
    if base.TOKEN in prompt:
        raise AssertionError("trigger prompt leaked the conversation-only token")
    return prompt


def arm_expected_reply(round_index: int) -> str:
    return f"{ARM_ACK_PREFIX}_{round_index:02d}"


def build_arm_prompt(round_index: int) -> str:
    expected = arm_expected_reply(round_index)
    prompt = (
        "Do not call tools. "
        f"Reply exactly {expected}."
    )
    if base.TOKEN in prompt:
        raise AssertionError("arm prompt leaked the conversation-only token")
    return prompt


def should_arm_before_next_fine(
    margin_to_trigger: int,
    previous_fine_step: int | None,
) -> bool:
    if margin_to_trigger <= 0:
        return False

    if margin_to_trigger <= DEFAULT_ARM_GUARD_TOKENS:
        return True

    if previous_fine_step is None or previous_fine_step <= 0:
        return False

    # Leave one observed fine-step plus the fixed guard as headroom. The live
    # body_after_prefix probe can fail before emitting usage when another ~858
    # token fine turn lands too close to the hard-context trigger. Switching to
    # tiny arm turns slightly earlier preserves the same thread while avoiding
    # an oversized boundary-crossing filler.
    return (
        margin_to_trigger
        <= previous_fine_step + DEFAULT_ARM_GUARD_TOKENS
    )



def transition_target_bytes(
    *,
    margin_to_trigger: int,
    previous_fine_step: int | None,
    fine_bytes: int,
    reserve_tokens: int = DEFAULT_TRANSITION_RESERVE_TOKENS,
) -> int | None:
    """Choose one medium filler before tiny arm turns.

    The live probe observed a ~858-token step from a 2048-byte fine filler and
    only ~48 tokens from each tiny arm turn. When the remaining margin is still
    hundreds of tokens, jumping directly to tiny arm turns can consume many web
    requests and hit account-side rate limits.

    Estimate a medium filler from the last measured fine-step slope while
    reserving a fixed token cushion before the trigger boundary. Return None
    when the safe estimate would be smaller than the minimum dense filler.
    """

    if (
        margin_to_trigger <= reserve_tokens
        or previous_fine_step is None
        or previous_fine_step <= 0
        or fine_bytes < DEFAULT_TRANSITION_MIN_BYTES
    ):
        return None

    desired_step = margin_to_trigger - reserve_tokens
    target = int(
        fine_bytes
        * desired_step
        / previous_fine_step
    )

    target = min(
        target,
        fine_bytes - 1,
    )

    if target < DEFAULT_TRANSITION_MIN_BYTES:
        return None

    return target


def build_transition_prompt(
    round_index: int,
    target_bytes: int,
) -> str:
    expected = f"AUTO_COMPACT_TRANSITION_ACK_{round_index:02d}"
    payload = _dense_deterministic_payload(
        round_index,
        target_bytes,
    )
    prompt = (
        "P1.2 auto-compaction transition filler.\n"
        "Do not call tools. Do not search files, logs, memory stores, or local "
        "session history. Treat the following deterministic material as context "
        "that must pass through the same Codex thread.\n"
        "--- BEGIN TRANSITION FILLER ---\n"
        + payload
        + "\n--- END TRANSITION FILLER ---\n"
        + f"Reply with exactly {expected} and nothing else."
    )
    if base.TOKEN in prompt:
        raise AssertionError(
            "transition prompt leaked the context token"
        )
    return prompt


def _dense_deterministic_payload(
    round_index: int,
    target_bytes: int,
) -> str:
    """Build token-dense deterministic Unicode with low browser character count.

    Every generated code point is inside the three-byte CJK Unified Ideographs
    block. This keeps roughly the same byte budget used by the acceptance
    harness while avoiding enormous ASCII transcripts when a resumed Codex CLI
    turn must replay full history through the ChatGPT Web composer.
    """

    if target_bytes < 1024:
        raise ValueError("target_bytes must be >= 1024")

    char_count = max(1, target_bytes // 3)
    first = 0x4E00
    span = 0x9FFF - first + 1

    state = (
        (int(round_index) * 0x9E3779B1)
        ^ 0xA5A5A5A5
    ) & 0xFFFFFFFF

    chars: list[str] = []

    for _ in range(char_count):
        state = (
            1664525 * state + 1013904223
        ) & 0xFFFFFFFF
        chars.append(chr(first + (state % span)))

    payload = "".join(chars)

    if len(payload.encode("utf-8")) > target_bytes:
        raise AssertionError("dense payload exceeded byte budget")

    return payload


def build_dense_filler_prompt(
    round_index: int,
    target_bytes: int,
) -> str:
    ack = f"LARGE_CONTEXT_FILLER_ACK_{round_index:02d}"
    payload = _dense_deterministic_payload(
        round_index,
        target_bytes,
    )

    prompt = (
        f"P1.2 synthetic dense context filler round {round_index}.\n"
        "Do not call tools. Do not search files, logs, memory stores, or local "
        "session history. Do not repeat or ask for any synthetic token from "
        "earlier turns. Treat the following deterministic material as context "
        "that must pass through the same Codex thread.\n"
        "--- BEGIN SYNTHETIC DENSE FILLER ---\n"
        + payload
        + "\n--- END SYNTHETIC DENSE FILLER ---\n"
        + f"Reply with exactly {ack} and nothing else."
    )

    if base.TOKEN in prompt:
        raise AssertionError(
            "dense filler prompt leaked the context token"
        )

    return prompt


def _read_jsonl(path: Path):
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for raw in lines:
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def count_rollout_compact_markers(path: Path) -> int:
    """Count rollout lines whose safe type metadata denotes compaction."""
    count = 0
    for obj in _read_jsonl(path) or ():
        types: list[str] = []
        outer = obj.get("type")
        if isinstance(outer, str):
            types.append(outer)
        payload = obj.get("payload")
        if isinstance(payload, dict):
            value = payload.get("type")
            if isinstance(value, str):
                types.append(value)
        msg = obj.get("msg")
        if isinstance(msg, dict):
            value = msg.get("type")
            if isinstance(value, str):
                types.append(value)
        if any("compact" in value.lower() for value in types):
            count += 1
    return count


def _find_private_rollout(thread_id: str) -> Path | None:
    roots = [
        Path.home() / ".codex" / "sessions",
        Path.home() / ".codex" / "archived_sessions",
    ]
    matches: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.jsonl"):
            if thread_id in path.name:
                matches.append(path)
    if not matches:
        for root in roots:
            if not root.exists():
                continue
            for path in root.rglob("*.jsonl"):
                try:
                    with path.open("r", encoding="utf-8", errors="replace") as handle:
                        prefix = handle.read(64 * 1024)
                except OSError:
                    continue
                if thread_id in prefix:
                    matches.append(path)
    if not matches:
        return None
    return max(set(matches), key=lambda path: path.stat().st_mtime)


def _wait_for_rollout(thread_id: str, timeout_sec: float = 5.0) -> Path | None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        path = _find_private_rollout(thread_id)
        if path is not None:
            return path
        time.sleep(0.25)
    return _find_private_rollout(thread_id)


def _run_turn_preserving_failure(**kwargs: Any) -> base.ExecObservation:
    return live.run_turn_preserving_failure_evidence(base._run_codex_turn, **kwargs)


def _safe_pre_submit_generation_block(
    observation: base.ExecObservation,
) -> bool:
    """Return True only when a turn provably never reached model execution."""

    return (
        observation.returncode != 0
        and PREEXISTING_GENERATION_MARKER in str(observation.raw or "")
        and not observation.agent_messages
        and observation.tool_effect_count == 0
        and not observation.input_tokens
        and not observation.output_tokens
    )


def _run_probe_turn(
    *,
    retry_delay_sec: float = DEFAULT_PRE_SUBMIT_RETRY_DELAY_SEC,
    **kwargs: Any,
) -> base.ExecObservation:
    """Retry once only for an exact, side-effect-free pre-submit UI block."""

    observation = _run_turn_preserving_failure(**kwargs)
    if (
        kwargs.get("thread_id") is None
        or not _safe_pre_submit_generation_block(observation)
    ):
        return observation

    print(
        "PRE_SUBMIT_RETRY=1 "
        "reason=preexisting_generation_no_dispatch"
    )
    if retry_delay_sec > 0:
        time.sleep(retry_delay_sec)

    retry_kwargs = dict(kwargs)
    trace_path = Path(retry_kwargs["trace_path"])
    retry_kwargs["trace_path"] = trace_path.with_name(
        trace_path.stem + "-retry.jsonl"
    )
    return _run_turn_preserving_failure(**retry_kwargs)


def _turn_ok(
    observation: base.ExecObservation,
    *,
    thread_id: str,
    expected_reply: str,
) -> bool:
    return (
        observation.returncode == 0
        and base._verify_thread(observation, thread_id)
        and observation.final_message == expected_reply
        and observation.tool_effect_count == 0
    )


def can_defer_trigger_reply(
    *,
    trigger_exact: bool,
    thread_matches: bool,
    tool_effect_count: int,
    compact_delta: int,
    remote_route_delta: int,
    remote_success_delta: int,
    token_leak: bool,
) -> bool:
    """Allow the trigger ACK to be proven by the following recovery turn.

    The trigger turn exists only to cross Codex's pre-turn compaction boundary.
    If native compaction and Remote V2 completion are both positively observed,
    the trigger produced no client-tool effects, thread identity is intact, and
    no synthetic token leaked to the workspace, the user-visible ACK may be
    absent. S3 must then prove usability with its strict same-thread
    post-compaction recovery gate.
    """

    return (
        not trigger_exact
        and thread_matches
        and tool_effect_count == 0
        and compact_delta > 0
        and remote_route_delta > 0
        and remote_success_delta > 0
        and not token_leak
    )


def _resolve_codex(codex: str) -> str | None:
    if os.sep in codex:
        path = Path(codex).expanduser()
        return str(path) if path.exists() else None
    return shutil.which(codex)


def run(
    root: Path,
    *,
    codex: str,
    uwa_log: Path,
    coarse_bytes: int,
    fine_bytes: int,
    coarse_guard_tokens: int,
    max_coarse_rounds: int,
    max_fine_rounds: int,
    timeout_sec: int,
    max_arm_rounds: int = DEFAULT_MAX_ARM_ROUNDS,
) -> int:
    root = base.prepare(root)
    codex_path = _resolve_codex(codex)
    if codex_path is None:
        print(f"RUN_FAIL codex_not_found={codex}")
        return 1

    context_window = base._query_context_window()
    if context_window is None:
        print("RUN_FAIL context_window_unavailable")
        return 1

    auto_limit = auto_compact_limit(context_window)
    hard_limit = hard_context_limit(context_window)
    compact_scope = configured_auto_compact_scope()
    trigger_limit = trigger_target_limit(context_window, compact_scope)
    if auto_limit >= hard_limit:
        print("RUN_FAIL invalid_threshold_order")
        return 1

    token_hits = base._workspace_contains_token(root)
    if token_hits:
        print("RUN_FAIL token_already_in_workspace=YES")
        return 1

    trace_dir = base._new_trace_dir()
    print(f"ROOT={root}")
    print(f"CONTEXT_WINDOW={context_window}")
    print(f"AUTO_COMPACT_LIMIT={auto_limit}")
    print(f"HARD_CONTEXT_LIMIT={hard_limit}")
    print(f"AUTO_COMPACT_SCOPE={compact_scope}")
    print(f"TRIGGER_TARGET_LIMIT={trigger_limit}")
    print(f"COARSE_BYTES={coarse_bytes}")
    print(f"FINE_BYTES={fine_bytes}")
    print(
        "COARSE_PROMPT_CHARS="
        + str(len(build_dense_filler_prompt(1, coarse_bytes)))
    )
    print(
        "FINE_PROMPT_CHARS="
        + str(len(build_dense_filler_prompt(1, fine_bytes)))
    )
    print(f"PRIVATE_TRACE_DIR={trace_dir}")

    seed = _run_turn_preserving_failure(
        codex=codex_path,
        root=root,
        prompt=base.build_seed_prompt(),
        trace_path=trace_dir / "trigger-probe-seed.jsonl",
        thread_id=None,
        timeout_sec=timeout_sec,
    )
    thread_ids = list(dict.fromkeys(seed.thread_ids))
    seed_exact = seed.final_message == "LARGE_CONTEXT_READY"
    print(f"SEED_REPLY_EXACT={'YES' if seed_exact else 'NO'}")
    print(f"SEED_TOOL_EFFECTS={seed.tool_effect_count}")
    print(f"PRIVATE_THREAD_CAPTURED={'YES' if len(thread_ids) == 1 else 'NO'}")
    if seed.returncode != 0 or not seed_exact or seed.tool_effect_count or len(thread_ids) != 1:
        print("RUN_FAIL seed_contract")
        return 1

    thread_id = thread_ids[0]
    previous_cumulative = cumulative_tokens(seed)
    if previous_cumulative is None:
        print("RUN_FAIL seed_usage_missing")
        return 1

    active_tokens = previous_cumulative
    round_index = 0

    for _ in range(max_coarse_rounds):
        if trigger_limit - active_tokens <= coarse_guard_tokens:
            break
        round_index += 1
        expected = f"LARGE_CONTEXT_FILLER_ACK_{round_index:02d}"
        observation = _run_probe_turn(
            codex=codex_path,
            root=root,
            prompt=build_dense_filler_prompt(round_index, coarse_bytes),
            trace_path=trace_dir / f"trigger-probe-{round_index:02d}-coarse.jsonl",
            thread_id=thread_id,
            timeout_sec=timeout_sec,
        )
        if observation.returncode != 0:
            print(
                f"RUN_FAIL coarse_turn_failed round={round_index} "
                f"rc={observation.returncode}"
            )
            return 1
        current_cumulative = cumulative_tokens(observation)
        if current_cumulative is None:
            print(f"RUN_FAIL coarse_usage_missing round={round_index}")
            return 1
        active_tokens = active_response_tokens(previous_cumulative, current_cumulative)
        previous_cumulative = current_cumulative
        exact = _turn_ok(observation, thread_id=thread_id, expected_reply=expected)
        print(
            f"PHASE=COARSE ROUND={round_index:02d} "
            f"ACK_EXACT={'YES' if exact else 'NO'} "
            f"ACTIVE_LAST_TOKENS={active_tokens} "
            f"MARGIN_TO_AUTO={auto_limit - active_tokens} "
            f"MARGIN_TO_TRIGGER={trigger_limit - active_tokens} "
            f"TOOL_EFFECTS={observation.tool_effect_count}"
        )
        if not exact:
            print(f"RUN_FAIL coarse_contract round={round_index}")
            return 1

    fine_rounds = 0
    previous_fine_step: int | None = None

    while active_tokens < trigger_limit and fine_rounds < max_fine_rounds:
        margin_to_trigger = trigger_limit - active_tokens

        if should_arm_before_next_fine(
            margin_to_trigger,
            previous_fine_step,
        ):
            print(
                "PHASE=FINE ARM_SWITCH=YES "
                f"MARGIN_TO_TRIGGER={margin_to_trigger} "
                f"PREVIOUS_FINE_STEP={previous_fine_step or 0}"
            )
            break

        fine_rounds += 1
        round_index += 1
        expected = f"LARGE_CONTEXT_FILLER_ACK_{round_index:02d}"
        previous_active_tokens = active_tokens

        observation = _run_probe_turn(
            codex=codex_path,
            root=root,
            prompt=build_dense_filler_prompt(round_index, fine_bytes),
            trace_path=trace_dir / f"trigger-probe-{round_index:02d}-fine.jsonl",
            thread_id=thread_id,
            timeout_sec=timeout_sec,
        )

        if observation.returncode != 0:
            print(
                f"RUN_FAIL fine_turn_failed round={round_index} "
                f"rc={observation.returncode}"
            )
            return 1
        current_cumulative = cumulative_tokens(observation)

        if current_cumulative is None:
            print(f"RUN_FAIL fine_usage_missing round={round_index}")
            return 1

        active_tokens = active_response_tokens(
            previous_cumulative,
            current_cumulative,
        )
        previous_cumulative = current_cumulative

        fine_step_tokens = max(
            0,
            active_tokens - previous_active_tokens,
        )

        if fine_step_tokens > 0:
            previous_fine_step = fine_step_tokens

        exact = _turn_ok(
            observation,
            thread_id=thread_id,
            expected_reply=expected,
        )

        print(
            f"PHASE=FINE ROUND={round_index:02d} "
            f"ACK_EXACT={'YES' if exact else 'NO'} "
            f"ACTIVE_LAST_TOKENS={active_tokens} "
            f"STEP_TOKENS={fine_step_tokens} "
            f"MARGIN_TO_AUTO={auto_limit - active_tokens} "
            f"MARGIN_TO_TRIGGER={trigger_limit - active_tokens} "
            f"TOOL_EFFECTS={observation.tool_effect_count}"
        )

        if not exact:
            print(f"RUN_FAIL fine_contract round={round_index}")
            return 1

    transition_margin = trigger_limit - active_tokens
    transition_bytes = transition_target_bytes(
        margin_to_trigger=transition_margin,
        previous_fine_step=previous_fine_step,
        fine_bytes=fine_bytes,
    )

    if transition_bytes is not None and active_tokens < trigger_limit:
        round_index += 1
        expected = f"AUTO_COMPACT_TRANSITION_ACK_{round_index:02d}"
        previous_active_tokens = active_tokens

        observation = _run_probe_turn(
            codex=codex_path,
            root=root,
            prompt=build_transition_prompt(
                round_index,
                transition_bytes,
            ),
            trace_path=trace_dir / f"trigger-probe-{round_index:02d}-transition.jsonl",
            thread_id=thread_id,
            timeout_sec=timeout_sec,
        )

        if observation.returncode != 0:
            print(
                f"RUN_FAIL transition_turn_failed round={round_index} "
                f"rc={observation.returncode}"
            )
            return 1
        current_cumulative = cumulative_tokens(observation)

        if current_cumulative is None:
            print(
                f"RUN_FAIL transition_usage_missing round={round_index}"
            )
            return 1

        active_tokens = active_response_tokens(
            previous_cumulative,
            current_cumulative,
        )
        previous_cumulative = current_cumulative

        transition_step_tokens = max(
            0,
            active_tokens - previous_active_tokens,
        )

        exact = _turn_ok(
            observation,
            thread_id=thread_id,
            expected_reply=expected,
        )

        print(
            f"PHASE=TRANSITION ROUND={round_index:02d} "
            f"ACK_EXACT={'YES' if exact else 'NO'} "
            f"TARGET_BYTES={transition_bytes} "
            f"ACTIVE_LAST_TOKENS={active_tokens} "
            f"STEP_TOKENS={transition_step_tokens} "
            f"MARGIN_TO_TRIGGER={trigger_limit - active_tokens} "
            f"TOOL_EFFECTS={observation.tool_effect_count}"
        )

        if not exact:
            print(
                f"RUN_FAIL transition_contract round={round_index}"
            )
            return 1

    arm_rounds = 0

    while active_tokens < trigger_limit and arm_rounds < max_arm_rounds:
        arm_rounds += 1
        round_index += 1
        expected = arm_expected_reply(round_index)
        previous_active_tokens = active_tokens

        observation = _run_probe_turn(
            codex=codex_path,
            root=root,
            prompt=build_arm_prompt(round_index),
            trace_path=trace_dir / f"trigger-probe-{round_index:02d}-arm.jsonl",
            thread_id=thread_id,
            timeout_sec=timeout_sec,
        )

        if observation.returncode != 0:
            print(
                f"RUN_FAIL arm_turn_failed round={round_index} "
                f"rc={observation.returncode}"
            )
            return 1
        current_cumulative = cumulative_tokens(observation)

        if current_cumulative is None:
            print(f"RUN_FAIL arm_usage_missing round={round_index}")
            return 1

        active_tokens = active_response_tokens(
            previous_cumulative,
            current_cumulative,
        )
        previous_cumulative = current_cumulative

        arm_step_tokens = max(
            0,
            active_tokens - previous_active_tokens,
        )

        exact = _turn_ok(
            observation,
            thread_id=thread_id,
            expected_reply=expected,
        )

        print(
            f"PHASE=ARM ROUND={round_index:02d} "
            f"ACK_EXACT={'YES' if exact else 'NO'} "
            f"ACTIVE_LAST_TOKENS={active_tokens} "
            f"STEP_TOKENS={arm_step_tokens} "
            f"MARGIN_TO_TRIGGER={trigger_limit - active_tokens} "
            f"TOOL_EFFECTS={observation.tool_effect_count}"
        )

        if not exact:
            print(f"RUN_FAIL arm_contract round={round_index}")
            return 1

    threshold_crossed = active_tokens >= trigger_limit
    print(f"THRESHOLD_CROSSED={'YES' if threshold_crossed else 'NO'}")
    print(f"PRE_TRIGGER_ACTIVE_TOKENS={active_tokens}")
    print(f"PRE_TRIGGER_OVER_HARD_CAP={'YES' if active_tokens >= hard_limit else 'NO'}")
    if not threshold_crossed:
        print("RUN_FAIL threshold_not_reached")
        return 1
    if compact_scope != "body_after_prefix" and active_tokens >= hard_limit:
        print("RUN_FAIL threshold_crossing_overshot_hard_cap")
        return 1
    if active_tokens >= context_window:
        print("RUN_FAIL threshold_crossing_overshot_raw_context")
        return 1

    rollout = _wait_for_rollout(thread_id)
    if rollout is None:
        print("RUN_FAIL rollout_not_found")
        return 1
    compact_before = count_rollout_compact_markers(rollout)
    print(f"PRE_TRIGGER_ROLLOUT_COMPACT_MARKERS={compact_before}")
    if compact_before:
        print("RUN_FAIL unexpected_pretrigger_compaction")
        return 1

    log_offset = uwa_log.stat().st_size if uwa_log.exists() else 0
    trigger = _run_turn_preserving_failure(
        codex=codex_path,
        root=root,
        prompt=build_trigger_prompt(),
        trace_path=trace_dir / "trigger-probe-final-trigger.jsonl",
        thread_id=thread_id,
        timeout_sec=timeout_sec,
    )
    trigger_exact = _turn_ok(trigger, thread_id=thread_id, expected_reply=TRIGGER_ACK)

    log_evidence = base.scan_log_delta(uwa_log, log_offset)
    time.sleep(0.5)
    compact_after = count_rollout_compact_markers(rollout)
    compact_delta = compact_after - compact_before

    trigger_thread_match = base._verify_thread(
        trigger,
        thread_id,
    )

    token_hits_after = base._workspace_contains_token(
        root
    )

    trigger_deferred = can_defer_trigger_reply(
        trigger_exact=trigger_exact,
        thread_matches=trigger_thread_match,
        tool_effect_count=trigger.tool_effect_count,
        compact_delta=compact_delta,
        remote_route_delta=log_evidence.route_markers,
        remote_success_delta=log_evidence.success_markers,
        token_leak=bool(token_hits_after),
    )

    print(f"TRIGGER_REPLY_EXACT={'YES' if trigger_exact else 'NO'}")
    print(
        "TRIGGER_THREAD_MATCH="
        + ("YES" if trigger_thread_match else "NO")
    )
    print(f"TRIGGER_TOOL_EFFECTS={trigger.tool_effect_count}")
    print(f"ROLLOUT_COMPACT_MARKER_DELTA={compact_delta}")
    print(f"REMOTE_COMPACT_ROUTE_DELTA={log_evidence.route_markers}")
    print(f"REMOTE_COMPACT_SUCCESS_DELTA={log_evidence.success_markers}")
    print(f"TOKEN_LEAK_WORKSPACE={'YES' if token_hits_after else 'NO'}")
    print(
        "TRIGGER_REPLY_DEFERRED_TO_POST_COMPACTION_RECOVERY="
        + ("YES" if trigger_deferred else "NO")
    )

    if token_hits_after:
        print("RUN_FAIL trigger_token_leak")
        return 1

    if not trigger_exact and not trigger_deferred:
        print("RUN_FAIL trigger_contract")
        return 1

    if compact_delta <= 0:
        print("RUN_FAIL auto_compact_lifecycle_not_observed")
        return 1

    if log_evidence.route_markers or log_evidence.success_markers:
        if not log_evidence.success_markers:
            print("RUN_FAIL remote_compact_route_without_success")
            return 1
        print("AUTO_COMPACT_MODE=REMOTE")
    else:
        print("AUTO_COMPACT_MODE=LOCAL_FALLBACK")

    print("AUTO_COMPACT_TRIGGER_PROBE_PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--root", type=Path, default=base.DEFAULT_ROOT)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--uwa-log", type=Path, default=base.DEFAULT_UWA_LOG)
    parser.add_argument("--coarse-bytes", type=int, default=DEFAULT_COARSE_BYTES)
    parser.add_argument("--fine-bytes", type=int, default=DEFAULT_FINE_BYTES)
    parser.add_argument("--coarse-guard-tokens", type=int, default=DEFAULT_COARSE_GUARD_TOKENS)
    parser.add_argument("--max-coarse-rounds", type=int, default=DEFAULT_MAX_COARSE_ROUNDS)
    parser.add_argument("--max-fine-rounds", type=int, default=DEFAULT_MAX_FINE_ROUNDS)
    parser.add_argument("--max-arm-rounds", type=int, default=DEFAULT_MAX_ARM_ROUNDS)
    parser.add_argument("--timeout-sec", type=int, default=DEFAULT_TIMEOUT_SEC)
    args = parser.parse_args()

    if args.coarse_bytes < 1024 or args.fine_bytes < 1024:
        raise SystemExit("filler bytes must be >= 1024")
    if args.coarse_guard_tokens < 1:
        raise SystemExit("--coarse-guard-tokens must be positive")
    if (
        args.max_coarse_rounds < 1
        or args.max_fine_rounds < 1
        or args.max_arm_rounds < 1
    ):
        raise SystemExit("round limits must be positive")

    return run(
        args.root,
        codex=args.codex,
        uwa_log=args.uwa_log.expanduser(),
        coarse_bytes=args.coarse_bytes,
        fine_bytes=args.fine_bytes,
        coarse_guard_tokens=args.coarse_guard_tokens,
        max_coarse_rounds=args.max_coarse_rounds,
        max_fine_rounds=args.max_fine_rounds,
        timeout_sec=args.timeout_sec,
        max_arm_rounds=args.max_arm_rounds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
