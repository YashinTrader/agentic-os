"""Persistent local supervisor — physical wake → claim → launch → complete."""

from __future__ import annotations

import json
import signal
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from dispatch.agent_wake import read_wake_signal
from dispatch.assignment_channel import claim_assignment, read_assignment, set_assignment_status
from dispatch.runtime_capture import run_directory
from dispatch.worktree_allocator import allocate_worktree
from orchestrator.agent_launcher import (
    build_codex_fallback_plan,
    build_grok_launch_plan,
    extract_session_id,
    launch_process,
)
from orchestrator.event_router import route_completion
from orchestrator.failure_classify import build_fingerprint, classify_process_output, should_relaunch
from orchestrator.leases import (
    DEFAULT_MAX_CONCURRENCY,
    has_assignment_lease,
    heartbeat_lease,
    release_lease,
    try_acquire_concurrency,
)
from orchestrator.process_monitor import mark_orphaned, monitor_process, pid_is_alive
from orchestrator.runtime_store import (
    STATE_BLOCKED_CAPACITY,
    STATE_BLOCKED_NO_ADAPTER,
    STATE_COMPLETED,
    STATE_FAILED_LAUNCH,
    STATE_LAUNCHING,
    STATE_QUEUED,
    STATE_RUNNING,
    STATE_MAX_TURNS,
    STATE_BLOCKED_EXTERNAL,
    FailureFingerprint,
    RunState,
    find_latest_run_for_assignment,
    save_run_state,
    utc_now,
)

STOP_REQUESTED = False


def _handle_stop(signum: int, frame: object) -> None:
    del signum, frame
    global STOP_REQUESTED
    STOP_REQUESTED = True


def generate_run_id(task_id: str) -> str:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    safe = "".join(c if c.isalnum() or c in "._-" else "-" for c in task_id)[:24]
    return f"phys-{stamp}-{safe}-{uuid.uuid4().hex[:8]}"


@dataclass
class SupervisorConfig:
    agent: str = "composer"
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY
    poll_seconds: int = 5
    max_turns: int = 30
    timeout_seconds: int = 1800
    allow_codex_fallback: bool = True
    max_automatic_retry: int = 1
    worktree: str | None = None
    grok_executable: str | None = None
    codex_executable: str | None = None


def _wake_queue(repo_root: Path, agent: str) -> Path:
    return repo_root / "runtime" / "dispatch" / "wake_queue" / agent


def _consume_wake(repo_root: Path, path: Path) -> None:
    consumed = repo_root / "runtime" / "dispatch" / "wake_queue" / "consumed" / path.name
    consumed.parent.mkdir(parents=True, exist_ok=True)
    path.replace(consumed)


def _default_prompt(assignment_id: str, task_id: str, task_path: str) -> str:
    return (
        f"You are the assigned builder for Agentic OS assignment {assignment_id} "
        f"(task {task_id}). Read the assignment contract and task YAML at {task_path}. "
        "Implement only within allowed paths. Do not merge, push to protected branches, "
        "or deploy. Produce a handoff when done."
    )


def _continuation_prompt(previous: RunState, task_path: str) -> str:
    return (
        f"Continue assignment {previous.assignment_id} (task {previous.task_id}) in the existing "
        f"worktree. Prior run {previous.run_id} reached its turn limit after making committed "
        f"progress on branch {previous.branch}. Inspect prior commits and the working tree, then "
        f"finish the remaining contract in {task_path}. Do not discard prior work."
    )


def _failure_from_state(state: RunState) -> FailureFingerprint | None:
    if not state.failure_fingerprint:
        return None
    data = state.failure_fingerprint
    try:
        return FailureFingerprint(
            agent=str(data.get("agent", "")),
            adapter=str(data.get("adapter", "")),
            failure_category=str(data.get("failure_category", "")),
            cli_exit_code=data.get("cli_exit_code"),
            normalized_error_type=str(data.get("normalized_error_type", "")),
            retry_after=data.get("retry_after"),
        )
    except Exception:
        return None


def process_wake_signal(
    repo_root: Path,
    signal_path: Path,
    *,
    config: SupervisorConfig,
    popen: Callable[..., Any] | None = None,
    monitor: Callable[..., Any] | None = None,
    launch_plan_builder: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Consume one wake signal and physically launch the assigned agent if eligible."""
    signal = read_wake_signal(signal_path)
    assignment_id = str(signal.get("assignment_id", ""))
    task_id = str(signal.get("task_id", ""))
    agent_id = str(signal.get("agent_id", config.agent))
    adapter_id = str(signal.get("adapter_id", ""))
    task_path = str(signal.get("task_path", ""))

    if not assignment_id:
        return {"status": "error", "reason": "wake signal missing assignment_id"}

    # Never relaunch completed/awaiting review work.
    existing = find_latest_run_for_assignment(repo_root, assignment_id)
    if existing and existing.process_state == STATE_COMPLETED:
        _consume_wake(repo_root, signal_path)
        return {
            "status": "skipped",
            "reason": "assignment already completed; will not relaunch",
            "assignment_id": assignment_id,
            "run_id": existing.run_id,
        }

    if has_assignment_lease(repo_root, assignment_id):
        return {
            "status": "skipped",
            "reason": "duplicate launch prevented; lease active",
            "assignment_id": assignment_id,
        }

    if existing and existing.process_state in {
        "blocked_authentication",
        "blocked_quota",
        "blocked_no_adapter",
        "failed",
        "failed_launch",
        "timed_out",
    }:
        prev_fp = _failure_from_state(existing)
        # Pre-check relaunch eligibility with same fingerprint before starting.
        ok, why = should_relaunch(
            previous=prev_fp,
            current=prev_fp,
            retry_count=existing.retry_count,
            max_automatic_retry=config.max_automatic_retry,
        )
        if not ok:
            _consume_wake(repo_root, signal_path)
            return {
                "status": "skipped",
                "reason": why,
                "assignment_id": assignment_id,
                "run_id": existing.run_id,
                "process_state": existing.process_state,
            }

    run_id = generate_run_id(task_id or assignment_id)
    lease, lease_reason = try_acquire_concurrency(
        repo_root,
        assignment_id=assignment_id,
        run_id=run_id,
        holder="supervisor",
        max_concurrency=config.max_concurrency,
    )
    if lease is None:
        state = RunState(
            run_id=run_id,
            assignment_id=assignment_id,
            task_id=task_id,
            assigned_agent=agent_id,
            adapter=adapter_id,
            process_state=STATE_BLOCKED_CAPACITY if "capacity" in lease_reason else STATE_QUEUED,
            blocked_reason=lease_reason,
            wake_signal_path=str(signal_path),
        )
        save_run_state(repo_root, state)
        return {"status": "deferred", "reason": lease_reason, "assignment_id": assignment_id, "run_id": run_id}

    # Atomic claim of the assignment for the assigned builder.
    record, claim_errors = claim_assignment(repo_root, assignment_id, claimed_by=agent_id)
    if record is None:
        # Already claimed by this agent in this session is OK if status is claimed/building.
        record, _ = read_assignment(repo_root, assignment_id)
        if record is None or record.assigned_to != agent_id or record.status not in {
            "claimed",
            "building",
            "changes_requested",
        }:
            release_lease(repo_root, assignment_id)
            return {
                "status": "error",
                "reason": "; ".join(claim_errors) or "claim failed",
                "assignment_id": assignment_id,
            }

    set_assignment_status(repo_root, assignment_id, "building")

    is_continuation = bool(existing and existing.process_state == STATE_MAX_TURNS)
    if is_continuation:
        worktree = Path(existing.worktree)
        branch_name = existing.branch
    elif config.worktree:
        worktree = Path(config.worktree).resolve()
        if worktree == repo_root.resolve():
            release_lease(repo_root, assignment_id)
            return {"status": "error", "reason": "canonical repo cannot be used as a build worktree"}
        branch_name = record.new_branch
    else:
        allocation = allocate_worktree(
            repo_root, task_id=task_id or record.task_id, run_id=run_id,
            base_sha=record.base_sha, base_branch=record.base_branch,
            owner="supervisor", cleanup_policy="preserve",
        )
        if not allocation.success:
            release_lease(repo_root, assignment_id)
            return {"status": "error", "reason": "; ".join(allocation.errors), "run_id": run_id}
        worktree = Path(allocation.worktree_path)
        branch_name = allocation.branch_name

    state = RunState(
        run_id=run_id,
        assignment_id=assignment_id,
        task_id=task_id or record.task_id,
        assigned_agent=agent_id,
        adapter=adapter_id or record.adapter_id,
        process_state=STATE_QUEUED,
        worktree=str(worktree),
        branch=branch_name,
        base_sha=record.base_sha,
        wake_signal_path=signal_path.relative_to(repo_root).as_posix()
        if signal_path.is_relative_to(repo_root)
        else str(signal_path),
        retry_count=(existing.retry_count + 1) if existing else 0,
        fallback_from_run_id=existing.run_id if existing else None,
        continuation_from_run_id=existing.run_id if is_continuation else None,
        auto_resume_count=(existing.auto_resume_count + 1) if is_continuation else 0,
    )
    save_run_state(repo_root, state)

    prompt = (
        _continuation_prompt(existing, task_path or record.task_path)
        if is_continuation and existing
        else _default_prompt(assignment_id, state.task_id, task_path or record.task_path)
    )
    builder = launch_plan_builder or build_grok_launch_plan
    plan = builder(
        worktree=worktree,
        prompt=prompt,
        max_turns=config.max_turns,
        timeout_hint_seconds=config.timeout_seconds,
        grok_executable=config.grok_executable,
    )

    used_fallback = False
    if (not plan.ok) and config.allow_codex_fallback:
        # Fallback only for missing adapter / unavailable Grok — not builder-to-builder reassignment.
        # Claude remains authority for formal reassignment; this is process fallback for one run.
        task_file = (repo_root / (task_path or record.task_path)).resolve()
        out_path = run_directory(repo_root, run_id) / "codex_agent_output.json"
        plan = build_codex_fallback_plan(
            repo_root=repo_root,
            worktree=worktree,
            task_path=task_file,
            agent_output_path=out_path,
            codex_executable=config.codex_executable,
        )
        used_fallback = True
        state.fallback_to_agent = "codex"
        state.assigned_agent = "codex"
        state.adapter = "codex-restricted"

    if not plan.ok:
        state.process_state = STATE_BLOCKED_NO_ADAPTER if "blocked_no_adapter" in ";".join(plan.blocked_reasons) else STATE_FAILED_LAUNCH
        state.blocked_reason = "; ".join(plan.blocked_reasons)
        state.completed_at = utc_now()
        state.retry_eligible = False
        save_run_state(repo_root, state)
        route, route_errors = route_completion(repo_root, state, branch=state.branch, source="composer")
        release_lease(repo_root, assignment_id)
        _consume_wake(repo_root, signal_path)
        return {
            "status": "blocked",
            "assignment_id": assignment_id,
            "run_id": run_id,
            "process_state": state.process_state,
            "reason": state.blocked_reason,
            "route": route,
            "route_errors": route_errors,
            "used_fallback": used_fallback,
        }

    run_dir = run_directory(repo_root, run_id)
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    state.process_state = STATE_LAUNCHING
    state.executable = plan.executable
    state.executable_version = plan.executable_version
    state.command_redacted = list(plan.command_redacted)
    state.started_at = utc_now()
    state.stdout_path = stdout_path.relative_to(repo_root).as_posix() if stdout_path.is_relative_to(repo_root) else str(stdout_path)
    state.stderr_path = stderr_path.relative_to(repo_root).as_posix() if stderr_path.is_relative_to(repo_root) else str(stderr_path)
    save_run_state(repo_root, state)

    handle, launch_msg = launch_process(plan, stdout_path=stdout_path, stderr_path=stderr_path, popen=popen)
    if handle is None:
        state.process_state = STATE_FAILED_LAUNCH
        state.blocked_reason = launch_msg
        state.completed_at = utc_now()
        save_run_state(repo_root, state)
        route, route_errors = route_completion(repo_root, state, branch=state.branch, source=state.assigned_agent)
        release_lease(repo_root, assignment_id)
        _consume_wake(repo_root, signal_path)
        return {
            "status": "failed_launch",
            "assignment_id": assignment_id,
            "run_id": run_id,
            "reason": launch_msg,
            "route": route,
            "route_errors": route_errors,
        }

    # Only after a real PID exists may state become running.
    state.pid = handle.pid
    state.session_id = handle.session_id
    state.process_state = STATE_RUNNING
    state.heartbeat_at = utc_now()
    save_run_state(repo_root, state)
    heartbeat_lease(repo_root, assignment_id, pid=handle.pid)

    monitor_fn = monitor or monitor_process
    mon = monitor_fn(
        handle.process,
        state=state,
        repo_root=repo_root,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout_seconds=config.timeout_seconds,
    )

    # Reload state after monitor heartbeats.
    state.exit_code = mon.exit_code
    state.completed_at = utc_now()
    if not state.session_id:
        state.session_id = extract_session_id(mon.stdout, mon.stderr)

    classification = classify_process_output(
        agent=state.assigned_agent,
        adapter=state.adapter,
        exit_code=mon.exit_code,
        stdout=mon.stdout,
        stderr=mon.stderr,
        timed_out=mon.timed_out,
    )
    state.process_state = classification.process_state if classification.process_state != "completed" else STATE_COMPLETED
    state.blocked_reason = classification.detail if state.process_state != STATE_COMPLETED else ""
    state.retry_eligible = classification.retry_eligible
    fp = build_fingerprint(
        agent=state.assigned_agent,
        adapter=state.adapter,
        classification=classification,
        exit_code=mon.exit_code,
    )
    state.failure_fingerprint = fp.to_dict() if classification.category != "completed" else None

    if state.process_state == STATE_MAX_TURNS:
        save_run_state(repo_root, state)
        release_lease(repo_root, assignment_id)
        if state.auto_resume_count < 1:
            return {
                "status": "requeued_continuation", "assignment_id": assignment_id,
                "run_id": run_id, "worktree": str(worktree), "branch": state.branch,
            }
        state.process_state = STATE_BLOCKED_EXTERNAL
        state.blocked_reason = "automatic max-turn continuation budget exhausted"
        state.retry_eligible = False

    # Codex fallback after Grok quota/auth/unavailable — one time max, no loops.
    if (
        state.process_state in {"blocked_quota", "blocked_authentication", STATE_BLOCKED_NO_ADAPTER, STATE_FAILED_LAUNCH}
        and config.allow_codex_fallback
        and not used_fallback
        and state.assigned_agent in {"composer", "grok"}
    ):
        prev = _failure_from_state(existing) if existing else None
        ok, why = should_relaunch(
            previous=prev,
            current=fp,
            retry_count=state.retry_count,
            max_automatic_retry=config.max_automatic_retry,
        )
        if ok and classification.category in {
            "blocked_quota",
            "blocked_authentication",
            "failed_launch",
            "blocked_no_adapter",
        }:
            # Record primary failure then launch codex once as fallback lineage.
            save_run_state(repo_root, state)
            fallback_run = generate_run_id(state.task_id)
            task_file = (repo_root / (task_path or record.task_path)).resolve()
            out_path = run_directory(repo_root, fallback_run) / "codex_agent_output.json"
            cplan = build_codex_fallback_plan(
                repo_root=repo_root,
                worktree=worktree,
                task_path=task_file,
                agent_output_path=out_path,
                codex_executable=config.codex_executable,
            )
            if cplan.ok:
                # Preserve lineage on a new run state.
                fb_state = RunState(
                    run_id=fallback_run,
                    assignment_id=assignment_id,
                    task_id=state.task_id,
                    assigned_agent="codex",
                    adapter="codex-restricted",
                    process_state=STATE_LAUNCHING,
                    worktree=str(worktree),
                    branch=record.new_branch,
                    base_sha=record.base_sha,
                    fallback_from_run_id=state.run_id,
                    retry_count=state.retry_count,
                    started_at=utc_now(),
                    executable=cplan.executable,
                    executable_version=cplan.executable_version,
                    command_redacted=list(cplan.command_redacted),
                )
                fb_stdout = run_directory(repo_root, fallback_run) / "stdout.log"
                fb_stderr = run_directory(repo_root, fallback_run) / "stderr.log"
                fb_state.stdout_path = fb_stdout.relative_to(repo_root).as_posix()
                fb_state.stderr_path = fb_stderr.relative_to(repo_root).as_posix()
                save_run_state(repo_root, fb_state)
                fb_handle, fb_msg = launch_process(
                    cplan, stdout_path=fb_stdout, stderr_path=fb_stderr, popen=popen
                )
                if fb_handle is not None:
                    fb_state.pid = fb_handle.pid
                    fb_state.process_state = STATE_RUNNING
                    fb_state.heartbeat_at = utc_now()
                    save_run_state(repo_root, fb_state)
                    fb_mon = monitor_fn(
                        fb_handle.process,
                        state=fb_state,
                        repo_root=repo_root,
                        stdout_path=fb_stdout,
                        stderr_path=fb_stderr,
                        timeout_seconds=config.timeout_seconds,
                    )
                    fb_state.exit_code = fb_mon.exit_code
                    fb_state.completed_at = utc_now()
                    fb_class = classify_process_output(
                        agent="codex",
                        adapter="codex-restricted",
                        exit_code=fb_mon.exit_code,
                        stdout=fb_mon.stdout,
                        stderr=fb_mon.stderr,
                        timed_out=fb_mon.timed_out,
                    )
                    fb_state.process_state = (
                        STATE_COMPLETED if fb_class.process_state == "completed" else fb_class.process_state
                    )
                    fb_state.blocked_reason = fb_class.detail if fb_state.process_state != STATE_COMPLETED else ""
                    fb_fp = build_fingerprint(
                        agent="codex",
                        adapter="codex-restricted",
                        classification=fb_class,
                        exit_code=fb_mon.exit_code,
                    )
                    fb_state.failure_fingerprint = (
                        fb_fp.to_dict() if fb_class.category != "completed" else None
                    )
                    save_run_state(repo_root, fb_state)
                    route, route_errors = route_completion(
                        repo_root, fb_state, branch=state.branch, source="codex"
                    )
                    release_lease(repo_root, assignment_id)
                    _consume_wake(repo_root, signal_path)
                    return {
                        "status": "completed" if fb_state.process_state == STATE_COMPLETED else fb_state.process_state,
                        "assignment_id": assignment_id,
                        "run_id": fb_state.run_id,
                        "pid": fb_state.pid,
                        "process_state": fb_state.process_state,
                        "fallback_from_run_id": state.run_id,
                        "used_fallback": True,
                        "route": route,
                        "route_errors": route_errors,
                        "primary_failure": state.process_state,
                        "fallback_reason": why,
                    }

    save_run_state(repo_root, state)
    route, route_errors = route_completion(
        repo_root, state, branch=state.branch, source=state.assigned_agent
    )
    release_lease(repo_root, assignment_id)
    _consume_wake(repo_root, signal_path)
    return {
        "status": "completed" if state.process_state == STATE_COMPLETED else state.process_state,
        "assignment_id": assignment_id,
        "run_id": run_id,
        "pid": state.pid,
        "session_id": state.session_id,
        "process_state": state.process_state,
        "exit_code": state.exit_code,
        "used_fallback": used_fallback,
        "route": route,
        "route_errors": route_errors,
        "command_redacted": state.command_redacted,
    }


def recover_orphans(repo_root: Path) -> list[dict[str, Any]]:
    from orchestrator.runtime_store import list_supervisor_runs

    recovered: list[dict[str, Any]] = []
    for state in list_supervisor_runs(repo_root, limit=100):
        if state.process_state not in {STATE_RUNNING, STATE_LAUNCHING}:
            continue
        alive = pid_is_alive(state.pid or -1) if state.pid else False
        if alive is False:
            mark_orphaned(repo_root, state, detail=f"PID {state.pid} not alive")
            release_lease(repo_root, state.assignment_id)
            recovered.append({"run_id": state.run_id, "assignment_id": state.assignment_id, "status": "orphaned"})
    return recovered


def process_once(repo_root: Path, *, config: SupervisorConfig | None = None, **kwargs: Any) -> dict[str, Any]:
    cfg = config or SupervisorConfig()
    recover_orphans(repo_root)
    queue = _wake_queue(repo_root, cfg.agent)
    signals = sorted(queue.glob("*.json")) if queue.is_dir() else []
    if not signals:
        return {"status": "idle", "agent": cfg.agent}
    return process_wake_signal(repo_root, signals[0], config=cfg, **kwargs)


def run_forever(repo_root: Path, *, config: SupervisorConfig | None = None, **kwargs: Any) -> int:
    cfg = config or SupervisorConfig()
    global STOP_REQUESTED
    STOP_REQUESTED = False
    signal.signal(signal.SIGINT, _handle_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_stop)

    while not STOP_REQUESTED:
        report = process_once(repo_root, config=cfg, **kwargs)
        print(json.dumps(report, sort_keys=True, default=str), flush=True)
        if report.get("status") == "idle":
            time.sleep(max(1, cfg.poll_seconds))
        else:
            time.sleep(max(1, min(cfg.poll_seconds, 2)))
    return 0
