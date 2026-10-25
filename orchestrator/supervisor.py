"""Persistent local supervisor — physical wake → claim → launch → complete."""

from __future__ import annotations

import json
import os
import signal
import time
import uuid
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from root_paths import root_metadata

from orchestrator import layer_heartbeat
from dispatch import work_lock
from dispatch.atomic_io import atomic_write_json
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
from orchestrator.builder_condition import (
    apply_block_schedule,
    clock_from,
    maybe_record_recovery,
    reevaluate_blocked_builders,
)
from orchestrator.event_router import route_completion
from orchestrator.launch_failures import classify_launch_failure, executable_identity, alert_once
from orchestrator.failure_classify import Classification, build_fingerprint, classify_process_output, should_relaunch
from orchestrator.leases import (
    DEFAULT_MAX_CONCURRENCY,
    count_active_leases,
    has_assignment_lease,
    heartbeat_lease,
    release_lease,
    try_acquire_concurrency,
    assignment_lease_path,
)
from orchestrator.process_ownership import ownership_metadata, process_start_time
from orchestrator.quota_probe import paid_probe_status
from orchestrator.process_monitor import mark_orphaned, monitor_process, pid_is_alive, read_text
from orchestrator.runtime_store import (
    TERMINAL_STATES,
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


def _launch_agent_process(root, state, plan, *, stdout_path, stderr_path, popen):
    """Retain OSError identity even though the CLI launch helper returns text."""
    failure = None

    def spawn(*args, **kwargs):
        nonlocal failure
        try:
            return (popen or subprocess.Popen)(*args, **kwargs)
        except OSError as exc:
            failure = exc
            raise

    handle, message = launch_process(plan, stdout_path=stdout_path, stderr_path=stderr_path, popen=spawn)
    if handle is None:
        _classify_launch_denial(root, state, failure, message, plan.executable)
    return handle, message


def _classify_launch_denial(root: Path, state: RunState, exc: Exception | None,
                            message: str, executable: str) -> None:
    state.failure_class = classify_launch_failure(exc, message)
    state.retry_eligible = state.failure_class == 'TRANSIENT'
    if not state.retry_eligible:
        state.blocked_executable = executable_identity(executable or 'grok', root)
        state.blocked_reason = f'{message}; failure_class={state.failure_class}; executable={state.blocked_executable}'
        alert_once(root, ['agent_cli', state.failure_class, state.blocked_executable],
                   kind='agent_cli_launch_failure', failure_class=state.failure_class,
                   executable=state.blocked_executable, assignment_id=state.assignment_id,
                   run_id=state.run_id, reason=message)


def _exhaust_assignment(root: Path, assignment_id: str, reason: str) -> None:
    """Publish an actionable terminal failure, fenced to the current owner."""
    from orchestrator.runtime_store import list_supervisor_runs
    record, _ = read_assignment(root, assignment_id)
    if record is None or record.status not in {'pending', 'claimed', 'building', 'reviewable_failure', 'changes_requested'}:
        return
    logical_id = record.logical_task_id or record.task_id
    locks = work_lock.status(root, logical_id)
    states = [s for s in list_supervisor_runs(root, limit=None) if s.assignment_id == assignment_id]
    ids = sorted({s.run_id for s in states})
    if locks:
        lock = locks[0]
        if lock['assignment_id'] != assignment_id or lock['holder_agent'] != record.assigned_to:
            return
        state = next((s for s in states if s.run_id == lock['run_id']), None)
        if state and state.process_state in {STATE_RUNNING, STATE_LAUNCHING, STATE_QUEUED}:
            return
    else:
        state = states[0] if states else None
    if state is None:
        if locks and locks[0]['run_id']:
            return  # Missing run evidence never authorizes ending a possible live holder.
        # A wake may exhaust before any physical run exists.
        state = RunState(run_id=generate_run_id(record.task_id), assignment_id=assignment_id,
                         task_id=record.task_id, assigned_agent=record.assigned_to,
                         adapter=record.adapter_id)
        ids.append(state.run_id)
    if not locks or not locks[0]['run_id']:
        work_lock.acquire(root, logical_id, holder_agent=record.assigned_to, route='supervisor',
                          assignment_id=assignment_id, run_id=state.run_id, resume=True)
    state.logical_task_id = logical_id
    state.process_state = 'failed'
    state.retry_eligible = False
    state.completed_at = utc_now()
    state.blocked_reason = f'{reason}; run_ids={", ".join(ids)}; reviewer action required: inspect run evidence and authorize a retry or child assignment'
    save_run_state(root, state)
    route_completion(root, state, summary=state.blocked_reason, source=state.assigned_agent)


def _handle_stop(signum: int, frame: object) -> None:
    del signum, frame
    global STOP_REQUESTED
    STOP_REQUESTED = True
    layer_heartbeat.request_stop()


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
    max_condition_retries: int = 4
    now: Callable[[], Any] | None = None
    condition_probe: Callable[[str], bool] | None = None
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
    **kwargs: Any,
) -> dict[str, Any]:
    """Fence pre-launch cleanup to this attempt; never release a running holder."""
    attempt: dict[str, Any] = {"started": False}
    report: dict[str, Any] = {"status": "error", "reason": "pre-launch interrupted"}
    try:
        report = _process_wake_signal(repo_root, signal_path, config=config, attempt=attempt, **kwargs)
    except Exception as exc:
        if attempt["started"]:
            raise
        report = {"status": "error", "reason": str(exc),
                  "failure_class": classify_launch_failure(exc)}
        attempt['exception'] = exc
    finally:
        if not attempt["started"] and attempt.get("run_id"):
            from orchestrator.runtime_store import load_run_state
            try:
                state = load_run_state(repo_root, attempt["run_id"])
                if state and state.process_state in {STATE_QUEUED, STATE_LAUNCHING}:
                    state.process_state = STATE_FAILED_LAUNCH
                    state.completed_at = utc_now()
                    state.blocked_reason = str(report.get("reason", "pre-launch failure"))
                    state.logical_task_id = attempt.get("logical_id", "")
                    _classify_launch_denial(repo_root, state, attempt.get('exception'),
                                            state.blocked_reason, state.executable or config.grok_executable or '')
                    save_run_state(repo_root, state)
                    if state.failure_class != 'TRANSIENT' and attempt.get('lock_acquired'):
                        route_completion(repo_root, state, summary=state.blocked_reason, source=state.assigned_agent)
                        report.update(nonretryable=True, failure_class=state.failure_class)
                        attempt['preserve_lock'] = True
            except work_lock.WorkLockError as exc:
                report["cleanup_fenced"] = str(exc)
            finally:
                try:
                    if attempt.get("lock_acquired") and not attempt.get('preserve_lock'):
                        # Fence cleanup against a concurrent explicit supersede.
                        work_lock.release(
                            repo_root, attempt["logical_id"], actor="supervisor",
                            reason="pre-launch failure: " + str(report.get("reason", report["status"])),
                            assignment_id=attempt["assignment_id"], run_id=attempt["run_id"],
                        )
                except work_lock.WorkLockError as exc:
                    report["cleanup_fenced"] = str(exc)
                finally:
                    release_lease(repo_root, attempt["assignment_id"], run_id=attempt["run_id"])
            report.setdefault("run_id", attempt["run_id"])
    report["process_started"] = attempt["started"]
    if report.get('nonretryable') and signal_path.exists():
        _consume_wake(repo_root, signal_path)
    return report


def _process_wake_signal(
    repo_root: Path,
    signal_path: Path,
    *,
    config: SupervisorConfig,
    popen: Callable[..., Any] | None = None,
    monitor: Callable[..., Any] | None = None,
    launch_plan_builder: Callable[..., Any] | None = None,
    condition_retry_from: RunState | None = None,
    attempt: dict[str, Any],
    single_launch: bool = False,
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
    record, _ = read_assignment(repo_root, assignment_id)
    if record:
        if record.status == 'reviewable_failure' and existing and existing.failure_class in {'CONFIG', 'BLOCKED_SECURITY_POLICY'}:
            _consume_wake(repo_root, signal_path)
            return {'status': 'skipped', 'reason': 'launch failure requires reviewer action', 'nonretryable': True}
        # A refused prelaunch must not hide the physical owner that exhausted its budget.
        from orchestrator.runtime_store import load_run_state
        locks = work_lock.status(repo_root, record.logical_task_id or record.task_id)
        if locks and locks[0]['assignment_id'] == assignment_id:
            owner = load_run_state(repo_root, locks[0]['run_id'])
            if owner and owner.process_state == STATE_MAX_TURNS:
                _exhaust_assignment(repo_root, assignment_id, 'turn budget exhausted')
                _consume_wake(repo_root, signal_path)
                return {'status': 'skipped', 'reason': 'turn budget exhausted; reviewer action required',
                        'assignment_id': assignment_id, 'run_id': owner.run_id}
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

    if condition_retry_from is None and existing and existing.process_state in {
        "blocked_authentication",
        "blocked_quota",
        "failed",
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
            # Quota/auth retries have their own durable condition schedule; an
            # immediate duplicate wake is not exhaustion of that budget.
            if not existing.blocked_on:
                _exhaust_assignment(repo_root, assignment_id, 'automatic retries exhausted: ' + why)
            _consume_wake(repo_root, signal_path)
            return {
                "status": "skipped",
                "reason": why,
                "assignment_id": assignment_id,
                "run_id": existing.run_id,
                "process_state": existing.process_state,
            }

    def defer_capacity(reason: str) -> dict[str, Any]:
        # Preserve failure attempts; capacity waits never escalate to dead letter.
        retry = signal.get("retry", {})
        retry = dict(retry) if isinstance(retry, dict) else {}
        retry["next_attempt_at"] = (clock_from(config) + timedelta(seconds=10)).isoformat()
        signal["retry"] = retry
        atomic_write_json(signal_path, signal)
        layer_heartbeat.tick()
        return {"status": "deferred", "reason": reason, "assignment_id": assignment_id}

    if count_active_leases(repo_root) >= config.max_concurrency:
        return defer_capacity("blocked_capacity: maximum concurrency reached")
    run_id = generate_run_id(task_id or assignment_id)
    lease, lease_reason = try_acquire_concurrency(
        repo_root, assignment_id=assignment_id, run_id=run_id,
        holder="supervisor", max_concurrency=config.max_concurrency,
    )
    if lease is None:
        return defer_capacity(lease_reason)

    attempt.update(run_id=run_id, assignment_id=assignment_id)
    # Write evidence BEFORE any durable lock can refer to this run.
    prelaunch_state = RunState(
        run_id=run_id, assignment_id=assignment_id, task_id=task_id,
        assigned_agent=agent_id, adapter=adapter_id, process_state=STATE_QUEUED,
        owner_pid=os.getpid(), owner_start_time=process_start_time(os.getpid()),
        wake_signal_path=str(signal_path),
    )
    save_run_state(repo_root, prelaunch_state)

    # Atomic claim of the assignment for the assigned builder.
    record, claim_errors = claim_assignment(repo_root, assignment_id, claimed_by=agent_id)
    if record is not None:
        layer_heartbeat.tick(progress=True)
    if record is None:
        # Already claimed by this agent in this session is OK if status is claimed/building.
        record, _ = read_assignment(repo_root, assignment_id)
        retrying_prelaunch = bool(existing and existing.pid is None and existing.process_state in {
            STATE_FAILED_LAUNCH, STATE_BLOCKED_NO_ADAPTER,
        } and record and record.status == "reviewable_failure")
        if record is None or record.assigned_to != agent_id or (record.status not in {
            "claimed",
            "building",
            "changes_requested",
        } and not retrying_prelaunch):
            release_lease(repo_root, assignment_id, run_id=run_id)
            return {
                "status": "error",
                "reason": "; ".join(claim_errors) or "claim failed",
                "assignment_id": assignment_id,
            }

    try:
        logical_id = record.logical_task_id or record.task_id
        if condition_retry_from is not None:
            work_lock.supersede(
                repo_root, logical_id, actor="supervisor",
                reason="bounded condition retry reuses the preserved work lock",
                holder_agent=agent_id, route="supervisor", assignment_id=assignment_id,
                run_id=run_id, base_sha=record.base_sha,
                branch=condition_retry_from.branch or record.new_branch,
                expected_assignment_id=assignment_id, expected_run_id=condition_retry_from.run_id,
            )
        else:
            work_lock.acquire(repo_root, logical_id, holder_agent=agent_id, route="supervisor",
                              assignment_id=assignment_id, run_id=run_id, base_sha=record.base_sha,
                              branch=record.new_branch, resume=True)
        attempt.update(lock_acquired=True, logical_id=logical_id)
        prelaunch_state.logical_task_id = logical_id
        save_run_state(repo_root, prelaunch_state)
    except (work_lock.WorkLockError, OSError) as exc:
        release_lease(repo_root, assignment_id, run_id=run_id)
        return {"status": "error", "reason": str(exc), "assignment_id": assignment_id}
    set_assignment_status(repo_root, assignment_id, "building")

    preserved = condition_retry_from if condition_retry_from is not None else None
    is_continuation = preserved is None and bool(
        existing and existing.process_state in TERMINAL_STATES and existing.retry_eligible)
    if preserved is None and is_continuation and existing is not None:
        preserved = existing
    if preserved is not None and preserved.worktree:
        worktree = Path(preserved.worktree)
        branch_name = preserved.branch or record.new_branch
    elif config.worktree:
        worktree = Path(config.worktree).resolve()
        if worktree == repo_root.resolve():
            release_lease(repo_root, assignment_id, run_id=run_id)
            return {"status": "error", "reason": "canonical repo cannot be used as a build worktree"}
        branch_name = record.new_branch
    else:
        allocation = allocate_worktree(
            repo_root, task_id=task_id or record.task_id, run_id=run_id,
            base_sha=record.base_sha, base_branch=record.base_branch,
            owner="supervisor", cleanup_policy="preserve",
            standalone_clone=True,
        )
        if not allocation.success:
            release_lease(repo_root, assignment_id, run_id=run_id)
            return {"status": "error", "reason": "; ".join(allocation.errors), "run_id": run_id}
        worktree = Path(allocation.worktree_path)
        branch_name = allocation.branch_name

    state = RunState(
        run_id=run_id,
        assignment_id=assignment_id,
        task_id=task_id or record.task_id,
        assigned_agent=agent_id,
        adapter=adapter_id or record.adapter_id,
        logical_task_id=record.logical_task_id or record.task_id,
        process_state=STATE_QUEUED,
        owner_pid=os.getpid(), owner_start_time=process_start_time(os.getpid()),
        worktree=str(worktree),
        branch=branch_name,
        base_sha=record.base_sha,
        wake_signal_path=signal_path.relative_to(repo_root).as_posix()
        if signal_path.is_relative_to(repo_root)
        else str(signal_path),
        retry_count=(existing.retry_count + 1) if existing else 0,
        fallback_from_run_id=None if condition_retry_from is not None else (existing.run_id if existing else None),
        continuation_from_run_id=existing.run_id if is_continuation else None,
        auto_resume_count=(existing.auto_resume_count + 1) if is_continuation else 0,
    )
    if condition_retry_from is not None:
        state.blocked_on = condition_retry_from.blocked_on
        state.blocked_since = condition_retry_from.blocked_since
        state.attempts = condition_retry_from.attempts
        state.condition_retry_from_run_id = condition_retry_from.run_id
        state.fallback_from_run_id = None
    work_lock.heartbeat(repo_root, state.logical_task_id, run_id=run_id, branch=branch_name)
    save_run_state(repo_root, state)
    layer_heartbeat.tick(progress=True)

    task_file_rel = task_path or record.task_path
    from orchestrator.task_contract import prepare_contract, contract_prompt, ContractError
    from orchestrator.builder_isolation import standalone_workspace
    try:
        standalone_workspace(worktree)
        contract, contract_sha256 = prepare_contract(
            worktree, (repo_root / task_file_rel).read_bytes(),
            turn_budget=config.max_turns, handoff_path=record.handoff_path,
        )
        prompt = contract_prompt(contract)
    except (ContractError, OSError) as exc:
        state.process_state = STATE_FAILED_LAUNCH
        state.blocked_reason = str(exc)
        state.completed_at = utc_now()
        state.retry_eligible = False
        save_run_state(repo_root, state)
        route, errors = route_completion(repo_root, state, branch=state.branch, source=agent_id)
        return {'status': 'failed_launch', 'reason': str(exc), 'run_id': run_id,
                'assignment_id': assignment_id, 'route': route, 'route_errors': errors}
    # Hash is supervisor evidence, outside the builder's writable clone.
    atomic_write_json(run_directory(repo_root, run_id) / 'task_contract_receipt.json',
                      {'sha256': contract_sha256, 'contract': contract})
    required_mcp_servers = list(getattr(record, "required_mcp_servers", None) or [])
    prompt = contract_prompt(contract)
    if preserved is not None:
        prompt += f' Prior run {preserved.run_id} stopped. Resume existing work. Do not discard commits.'
    if condition_retry_from is not None and agent_id == "codex" and launch_plan_builder is None:
        task_file = (repo_root / task_file_rel).resolve()
        out_path = run_directory(repo_root, run_id) / "codex_agent_output.json"
        plan = build_codex_fallback_plan(
            repo_root=repo_root,
            worktree=worktree,
            task_path=task_file,
            agent_output_path=out_path,
            codex_executable=config.codex_executable,
            required_mcp_servers=required_mcp_servers,
        )
        state.assigned_agent = "codex"
        state.adapter = "codex-restricted"
    else:
        builder = launch_plan_builder or build_grok_launch_plan
        plan = builder(
            worktree=worktree,
            prompt=prompt,
            max_turns=config.max_turns,
            timeout_hint_seconds=config.timeout_seconds,
            grok_executable=config.grok_executable,
            required_mcp_servers=required_mcp_servers,
        )

    used_fallback = False
    plan.contract_sha256 = contract_sha256
    plan.env['AGENTIC_BUILDER_RUN_ID'] = run_id
    plan_failure_text = '; '.join(plan.blocked_reasons)
    plan_failure_exc = FileNotFoundError(plan_failure_text) if 'executable not found' in plan_failure_text.lower() else None
    plan_failure_class = classify_launch_failure(plan_failure_exc, plan_failure_text)
    if (not plan.ok) and config.allow_codex_fallback and plan_failure_class == 'TRANSIENT':
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
            required_mcp_servers=required_mcp_servers,
        )
        if plan.ok:
            work_lock.supersede(repo_root, state.logical_task_id, actor="supervisor",
                                reason="configured Codex fallback: primary adapter unavailable before launch",
                                holder_agent="codex", route="supervisor", assignment_id=assignment_id,
                                run_id=run_id, base_sha=record.base_sha, branch=state.branch,
                                expected_assignment_id=assignment_id, expected_run_id=run_id)
        used_fallback = True
        plan.contract_sha256 = contract_sha256
        plan.env['AGENTIC_BUILDER_RUN_ID'] = run_id
        state.fallback_to_agent = "codex"
        state.assigned_agent = "codex"
        state.adapter = "codex-restricted"

    if not plan.ok:
        state.process_state = STATE_BLOCKED_NO_ADAPTER if "blocked_no_adapter" in ";".join(plan.blocked_reasons) else STATE_FAILED_LAUNCH
        state.blocked_reason = "; ".join(plan.blocked_reasons)
        state.completed_at = utc_now()
        missing = 'executable not found' in state.blocked_reason.lower()
        configured_executable = (config.codex_executable or 'codex') if state.assigned_agent == 'codex' else (config.grok_executable or 'grok')
        _classify_launch_denial(repo_root, state, FileNotFoundError(state.blocked_reason) if missing else None,
                               state.blocked_reason, plan.executable or configured_executable)
        save_run_state(repo_root, state)
        layer_heartbeat.tick(progress=True)
        route, route_errors = ({}, [])
        if not state.retry_eligible:
            route, route_errors = route_completion(repo_root, state, branch=state.branch, source="composer")
            attempt['preserve_lock'] = True
        release_lease(repo_root, assignment_id, run_id=run_id)
        return {
            "status": "blocked",
            "assignment_id": assignment_id,
            "run_id": run_id,
            "process_state": state.process_state,
            "reason": state.blocked_reason,
            "route": route,
            "route_errors": route_errors,
            "used_fallback": used_fallback,
            "nonretryable": not state.retry_eligible,
            "failure_class": state.failure_class,
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
    layer_heartbeat.tick(progress=True)

    from orchestrator.builder_watch import state_snapshot, changed_state
    before_builder = state_snapshot(repo_root)
    from dispatch.worktree_allocator import resolve_worktree_root
    plan.env['AGENTIC_BUILDER_INVENTORY_ROOT'] = str(resolve_worktree_root(repo_root))
    handle, launch_msg = _launch_agent_process(repo_root, state, plan, stdout_path=stdout_path, stderr_path=stderr_path, popen=popen)
    if handle is None:
        state.process_state = STATE_FAILED_LAUNCH
        state.blocked_reason = launch_msg
        state.completed_at = utc_now()
        save_run_state(repo_root, state)
        layer_heartbeat.tick(progress=True)
        route, route_errors = ({}, [])
        if not state.retry_eligible:
            state.blocked_reason = f'{launch_msg}; failure_class={state.failure_class}; executable={state.blocked_executable}'
            save_run_state(repo_root, state)
            route, route_errors = route_completion(repo_root, state, branch=state.branch, source=state.assigned_agent)
            attempt['preserve_lock'] = True
        release_lease(repo_root, assignment_id, run_id=run_id)
        return {
            "status": "failed_launch",
            "assignment_id": assignment_id,
            "run_id": run_id,
            "reason": launch_msg,
            "route": route,
            "route_errors": route_errors,
            "nonretryable": not state.retry_eligible,
            "failure_class": state.failure_class,
        }

    # Only after a real PID exists may state become running.
    attempt["started"] = True
    state.pid = handle.pid
    for key, value in ownership_metadata(handle.process).items():
        setattr(state, key, value)
    state.session_id = handle.session_id
    state.process_state = STATE_RUNNING
    state.heartbeat_at = utc_now()
    save_run_state(repo_root, state)
    layer_heartbeat.tick(progress=True)
    heartbeat_lease(repo_root, assignment_id, pid=handle.pid)

    monitor_fn = monitor or monitor_process
    mon = monitor_fn(
        handle.process,
        state=state,
        repo_root=repo_root,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout_seconds=config.timeout_seconds,
        **({"started_monotonic": handle.started_monotonic,
            "initial_snapshot": handle.initial_snapshot, "builder_contract": contract} if monitor is None else {}),
    )
    maybe_record_recovery(state, now=clock_from(config))

    # Reload state after monitor heartbeats.
    state.exit_code = mon.exit_code
    state.completed_at = utc_now()
    if state.adapter == "composer-restricted":
        from orchestrator.grok_stream import record_terminal
        record_terminal(state, mon.stdout)
    elif not state.session_id:
        state.session_id = extract_session_id(mon.stdout, mon.stderr)

    classification = classify_process_output(
        agent=state.assigned_agent,
        adapter=state.adapter,
        exit_code=mon.exit_code,
        stdout=mon.stdout,
        stderr=mon.stderr,
        timed_out=mon.timed_out,
        deadline_state=getattr(mon, "deadline_state", None),
        required_mcp_servers=list(getattr(plan, "required_mcp_servers", None) or required_mcp_servers),
    )
    from orchestrator.builder_watch import BuilderWatch
    replay = BuilderWatch(worktree, contract, notify=lambda *_: None)
    replay.initial = handle.initial_snapshot or replay.initial
    for line in mon.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            replay.event(event)
    supervisor_paths = [f'runtime/dispatch/assignments/{kind}/{assignment_id}.json'
                        for kind in ('inbox', 'claims')]
    supervisor_paths.append(work_lock.lock_path(repo_root, state.logical_task_id).relative_to(repo_root).as_posix())
    try:
        changed = changed_state(before_builder, state_snapshot(repo_root), supervisor_paths)
    except OSError as exc:
        changed = ['snapshot_error: ' + str(exc)]
    diagnostic = {**replay.diagnostic(), 'changed_state_paths': changed}
    atomic_write_json(run_dir / 'builder_diagnostic.json', diagnostic)
    if changed or replay.outside:
        from orchestrator.launch_failures import alert_once
        alert_once(repo_root, [run_id, 'isolation_violation'], event='isolation_violation',
                   assignment_id=assignment_id, run_id=run_id, diagnostic=diagnostic)
        classification = Classification('failed', 'isolation_violation', json.dumps(diagnostic))
    elif classification.process_state == STATE_MAX_TURNS:
        classification = Classification('failed', 'completion_condition_unmet',
                                        'turn budget exhausted; reviewer action required: inspect preserved branch and run diagnostic; '
                                        + json.dumps(diagnostic))
    if popen is None and classification.process_state == STATE_COMPLETED:
        from orchestrator.builder_completion import verify_completion
        try:
            failures, acceptance_evidence = verify_completion(
                plan, contract, base_sha=state.base_sha, evidence_dir=run_dir)
            atomic_write_json(run_dir/'completion_checks.json',
                              {'failures': failures, 'acceptance': acceptance_evidence})
            if failures:
                classification = Classification('failed', 'completion_condition_unmet', '; '.join(failures))
            else:
                from dispatch.worktree_allocator import import_builder_results
                import_builder_results(repo_root, worktree, state.branch)
        except (OSError, ValueError) as exc:
            classification = Classification('failed', 'completion_verification_failed', str(exc))
    fp = _apply_classification(repo_root, state, classification, config=config)

    # Codex fallback after Grok quota/auth/unavailable — one time max, no loops.
    if (
        state.process_state in {"blocked_quota", "blocked_authentication", STATE_BLOCKED_NO_ADAPTER, STATE_FAILED_LAUNCH}
        and not state.deadline_fired
        and config.allow_codex_fallback
        and not used_fallback
        and not single_launch
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
            layer_heartbeat.tick(progress=True)
            fallback_run = generate_run_id(state.task_id)
            task_file = (repo_root / (task_path or record.task_path)).resolve()
            out_path = run_directory(repo_root, fallback_run) / "codex_agent_output.json"
            cplan = build_codex_fallback_plan(
                repo_root=repo_root,
                worktree=worktree,
                task_path=task_file,
                agent_output_path=out_path,
                codex_executable=config.codex_executable,
                required_mcp_servers=required_mcp_servers,
            )
            cplan.contract_sha256 = contract_sha256
            cplan.env['AGENTIC_BUILDER_RUN_ID'] = fallback_run
            if cplan.ok:
                # A fallback is a separate pre-launch attempt with its own evidence.
                attempt.update(started=False, run_id=fallback_run, lock_acquired=False)
                save_run_state(repo_root, RunState(
                    run_id=fallback_run, assignment_id=assignment_id, task_id=state.task_id,
                    assigned_agent="codex", adapter="codex-restricted", process_state=STATE_QUEUED,
                ))
                work_lock.supersede(repo_root, state.logical_task_id, actor="supervisor",
                                    reason=f"configured Codex fallback after primary exited: {state.process_state}",
                                    holder_agent="codex", route="supervisor", assignment_id=assignment_id,
                                    run_id=fallback_run, base_sha=record.base_sha, branch=state.branch,
                                    expected_assignment_id=assignment_id, expected_run_id=state.run_id)
                attempt["lock_acquired"] = True
                # Preserve lineage on a new run state.
                fb_state = RunState(
                    run_id=fallback_run,
                    assignment_id=assignment_id,
                    task_id=state.task_id,
                    logical_task_id=state.logical_task_id,
                    assigned_agent="codex",
                    adapter="codex-restricted",
                    process_state=STATE_LAUNCHING,
                    worktree=str(worktree),
                    branch=state.branch,
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
                layer_heartbeat.tick(progress=True)
                cplan.env['AGENTIC_BUILDER_INVENTORY_ROOT'] = str(resolve_worktree_root(repo_root))
                fb_handle, fb_msg = _launch_agent_process(
                    repo_root, fb_state, cplan, stdout_path=fb_stdout, stderr_path=fb_stderr, popen=popen
                )
                if fb_handle is None:
                    fb_state.process_state = STATE_FAILED_LAUNCH
                    fb_state.blocked_reason = fb_state.blocked_reason or fb_msg
                    fb_state.completed_at = utc_now()
                    save_run_state(repo_root, fb_state)
                    route, route_errors = route_completion(repo_root, fb_state, branch=state.branch, source="codex")
                    attempt['preserve_lock'] = not fb_state.retry_eligible
                    release_lease(repo_root, assignment_id, run_id=run_id)
                    _consume_wake(repo_root, signal_path)
                    return {"status": "failed_launch", "reason": fb_msg, "assignment_id": assignment_id,
                            "run_id": fallback_run, "route": route, "route_errors": route_errors,
                            "failure_class": fb_state.failure_class, "nonretryable": not fb_state.retry_eligible}
                if fb_handle is not None:
                    attempt["started"] = True
                    fb_state.pid = fb_handle.pid
                    for key, value in ownership_metadata(fb_handle.process).items():
                        setattr(fb_state, key, value)
                    fb_state.process_state = STATE_RUNNING
                    fb_state.heartbeat_at = utc_now()
                    save_run_state(repo_root, fb_state)
                    layer_heartbeat.tick(progress=True)
                    fb_mon = monitor_fn(
                        fb_handle.process,
                        state=fb_state,
                        repo_root=repo_root,
                        stdout_path=fb_stdout,
                        stderr_path=fb_stderr,
                        timeout_seconds=config.timeout_seconds,
                        **({"started_monotonic": fb_handle.started_monotonic,
                            "initial_snapshot": fb_handle.initial_snapshot,
                            "builder_contract": contract} if monitor is None else {}),
                    )
                    maybe_record_recovery(fb_state, now=clock_from(config))
                    fb_state.exit_code = fb_mon.exit_code
                    fb_state.completed_at = utc_now()
                    fb_class = classify_process_output(
                        agent="codex",
                        adapter="codex-restricted",
                        exit_code=fb_mon.exit_code,
                        stdout=fb_mon.stdout,
                        stderr=fb_mon.stderr,
                        timed_out=fb_mon.timed_out,
                        deadline_state=getattr(fb_mon, "deadline_state", None),
                        required_mcp_servers=list(
                            getattr(cplan, "required_mcp_servers", None) or required_mcp_servers
                        ),
                    )
                    fb_watch = BuilderWatch(worktree, contract, notify=lambda *_: None)
                    fb_watch.initial = fb_handle.initial_snapshot or fb_watch.initial
                    for line in fb_mon.stdout.splitlines():
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(event, dict):
                            fb_watch.event(event)
                    fb_changed = changed_state(before_builder, state_snapshot(repo_root), supervisor_paths)
                    fb_diagnostic = {**fb_watch.diagnostic(), 'changed_state_paths': fb_changed}
                    atomic_write_json(run_directory(repo_root, fallback_run)/'builder_diagnostic.json', fb_diagnostic)
                    if fb_changed or fb_watch.outside:
                        from orchestrator.launch_failures import alert_once
                        alert_once(repo_root, [fallback_run, 'isolation_violation'], event='isolation_violation',
                                   run_id=fallback_run, diagnostic=fb_diagnostic)
                        fb_class = Classification('failed', 'isolation_violation', json.dumps(fb_diagnostic))
                    elif fb_class.process_state == STATE_MAX_TURNS:
                        fb_class = Classification('failed', 'completion_condition_unmet',
                                                 'turn budget exhausted; reviewer action required: inspect preserved branch and run diagnostic; '
                                                 + json.dumps(fb_diagnostic))
                    elif popen is None and fb_class.process_state == STATE_COMPLETED:
                        from orchestrator.builder_completion import verify_completion
                        try:
                            failures, checks = verify_completion(cplan, contract, base_sha=state.base_sha,
                                                                 evidence_dir=run_directory(repo_root, fallback_run))
                            atomic_write_json(run_directory(repo_root, fallback_run)/'completion_checks.json',
                                              {'failures': failures, 'acceptance': checks})
                            if failures:
                                fb_class = Classification('failed', 'completion_condition_unmet', '; '.join(failures))
                            else:
                                from dispatch.worktree_allocator import import_builder_results
                                import_builder_results(repo_root, worktree, state.branch)
                        except (OSError, ValueError) as exc:
                            fb_class = Classification('failed', 'completion_verification_failed', str(exc))
                    fb_state.process_state = getattr(fb_mon, "deadline_state", None) or (
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
                    if not fb_state.deadline_fired:
                        apply_block_schedule(
                            repo_root,
                            fb_state,
                            retry_after=fb_class.retry_after,
                            now=clock_from(config),
                            max_attempts=config.max_condition_retries,
                        )
                    save_run_state(repo_root, fb_state)
                    layer_heartbeat.tick(progress=True)
                    route, route_errors = route_completion(
                        repo_root, fb_state, branch=state.branch, source="codex"
                    )
                    release_lease(repo_root, assignment_id, run_id=run_id)
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
    layer_heartbeat.tick(progress=True)
    route, route_errors = route_completion(
        repo_root, state, branch=state.branch, source=state.assigned_agent
    )
    release_lease(repo_root, assignment_id, run_id=run_id)
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


def _apply_classification(
    repo_root: Path, state: RunState, classification: Classification, *, config: SupervisorConfig,
) -> FailureFingerprint:
    """Use the same failure metadata and condition schedule for monitoring and salvage."""
    if classification.process_state == STATE_MAX_TURNS:
        classification = Classification('blocked_external', 'max_turns',
            'turn budget exhausted; reviewer action required: inspect preserved branch and run evidence before authorizing a retry')
    state.process_state = classification.process_state
    state.blocked_reason = (
        f"{state.deadline_fired} deadline expired" if state.deadline_fired else classification.detail
    ) if state.process_state != STATE_COMPLETED else ""
    state.retry_eligible = classification.retry_eligible
    fp = build_fingerprint(agent=state.assigned_agent, adapter=state.adapter,
                           classification=classification, exit_code=state.exit_code)
    state.failure_fingerprint = fp.to_dict() if classification.category != "completed" else None
    if not state.deadline_fired:
        apply_block_schedule(repo_root, state, retry_after=classification.retry_after,
                             now=clock_from(config), max_attempts=config.max_condition_retries)
    return fp


def recover_orphans(repo_root: Path, *, config: SupervisorConfig | None = None) -> list[dict[str, Any]]:
    from orchestrator.runtime_store import list_supervisor_runs, load_run_state

    cfg = config or SupervisorConfig()
    recovered: list[dict[str, Any]] = []
    for state in list_supervisor_runs(repo_root, limit=None):
        layer_heartbeat.tick()
        if state.process_state not in {STATE_RUNNING, STATE_LAUNCHING, STATE_QUEUED}:
            continue
        alive = pid_is_alive(state.pid or -1, state.process_start_time) if state.pid else False
        if alive is not False:
            continue
        if state.process_state in {STATE_QUEUED, STATE_LAUNCHING}:
            # Missing identity is unknown, never authority to reclaim a slot.
            if not state.owner_pid or pid_is_alive(state.owner_pid, state.owner_start_time) is not False:
                continue
            try:
                lease = json.loads(assignment_lease_path(repo_root, state.assignment_id).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                lease = {}
            if lease.get("pid") and pid_is_alive(lease["pid"], lease.get("process_start_time")) is not False:
                continue
            state.process_state = STATE_FAILED_LAUNCH
            state.blocked_reason = "builder layer exited before launch"
            state.completed_at = utc_now()
            state.retry_eligible = True
            try:
                save_run_state(repo_root, state)
                work_lock.release(repo_root, state.logical_task_id or state.task_id,
                                  actor="supervisor", reason=state.blocked_reason,
                                  assignment_id=state.assignment_id, run_id=state.run_id)
            except work_lock.WorkLockError:
                save_run_state(repo_root, state, refresh_work_lock=False)
                # Replacement work lock is never ours to release.
            release_lease(repo_root, state.assignment_id, run_id=state.run_id)
            wake = Path(state.wake_signal_path)
            if not wake.is_absolute():
                wake = repo_root / wake
            if wake.is_file():
                _retry_wake(repo_root, wake, {"status": "failed_launch", "reason": state.blocked_reason}, config=cfg)
            recovered.append({"run_id": state.run_id, "status": state.process_state})
            continue
        assignment, _ = read_assignment(repo_root, state.assignment_id)
        classification = classify_process_output(
            agent=state.assigned_agent, adapter=state.adapter, exit_code=None,
            stdout=read_text(repo_root / state.stdout_path) if state.stdout_path else "",
            stderr=read_text(repo_root / state.stderr_path) if state.stderr_path else "",
            required_mcp_servers=list(getattr(assignment, "required_mcp_servers", None) or []),
        )
        if classification.process_state in {"blocked_quota", "blocked_authentication", "blocked_external", STATE_MAX_TURNS}:
            state.exit_code = None
            state.completed_at = utc_now()
            _apply_classification(repo_root, state, classification, config=cfg)
            try:
                save_run_state(repo_root, state)
            except work_lock.WorkLockError:
                # An explicit replacement owns this task now. Do not publish an
                # outcome or change its assignment/lease on the dead run's behalf.
                recovered.append({"run_id": state.run_id, "status": "fenced"})
                continue
            route_completion(repo_root, state, branch=state.branch, source=state.assigned_agent)
        else:
            mark_orphaned(repo_root, state, detail=f"PID {state.pid} not alive")
            try:
                work_lock.release(repo_root, state.logical_task_id or state.task_id,
                                  actor="supervisor", reason="orphan_recovered", run_id=state.run_id)
            except work_lock.WorkLockError:
                pass  # Fenced release: a different holder must remain untouched.
        # Release only this run's concurrency lease, never a replacement's.
        try:
            lease = json.loads(assignment_lease_path(repo_root, state.assignment_id).read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            lease = {}
        if lease.get("run_id") == state.run_id:
            release_lease(repo_root, state.assignment_id, run_id=state.run_id)
        recovered.append({"run_id": state.run_id, "assignment_id": state.assignment_id, "status": state.process_state})

    # Recovery above can release newly orphaned holders. Pre-existing terminal
    # holders are alerted only; their age/state never grants permission to steal.
    ghosts = []
    for lock in work_lock.status(repo_root):
        run_id = lock.get("run_id")
        if not run_id:
            continue
        run_dir = repo_root / "runtime/dispatch/runs" / run_id
        state = load_run_state(repo_root, run_id)
        if state is not None:
            if state.process_state not in {"orphaned", "failed_launch", "blocked_external"}:
                continue
            if state.pid and pid_is_alive(state.pid, state.process_start_time) is not False:
                continue
        elif (run_dir / "result.json").is_file():
            try:
                result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if result.get("process_state", result.get("status")) not in {"orphaned", "failed_launch", "blocked_external"}:
                continue
            if result.get("pid") and pid_is_alive(result["pid"], result.get("process_start_time")) is not False:
                continue
        elif (run_dir / "supervisor_run.json").is_file():
            continue  # Unreadable evidence cannot establish a terminal state.
        try:
            lease = json.loads(assignment_lease_path(repo_root, lock["assignment_id"]).read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            lease = {}
        if lease.get("run_id") == run_id and lease.get("pid"):
            if pid_is_alive(lease["pid"], lease.get("process_start_time")) is not False:
                continue
        if lock.get("pid") and pid_is_alive(lock["pid"], lock.get("process_start_time")) is not False:
            continue
        try:
            work_lock.report_ghost(repo_root, lock["logical_task_id"], run_id=run_id)
        except work_lock.WorkLockError:
            continue  # Ownership may have changed since the status snapshot.
        alert = {"status": "stale", "reason": "ghost_holder", "run_id": run_id,
                 "assignment_id": lock["assignment_id"], "logical_task_id": lock["logical_task_id"]}
        ghosts.append(alert)
        recovered.append(alert)
    _update_status(repo_root, work_lock_alerts=ghosts)
    return recovered


def _update_status(repo_root: Path, **updates: Any) -> None:
    path = repo_root / "runtime/dispatch/supervisor_status.json"
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        status = {}
    status.update(updates)
    atomic_write_json(path, status)


def _retry_wake(repo_root: Path, path: Path, report: dict[str, Any], *, config: SupervisorConfig) -> None:
    """Three failures, exponential backoff, then durable dead-letter evidence."""
    try:
        signal = read_wake_signal(path)
        if not isinstance(signal, dict):
            signal = {"invalid_signal": signal}
    except ValueError:
        signal = {"invalid_signal": path.read_text(encoding="utf-8")}
    previous = signal.get("retry", {})
    if not isinstance(previous, dict):
        previous = {}
    try:
        attempts = min(3, max(0, int(previous.get("attempts", 0))) + 1)
    except (TypeError, ValueError):
        attempts = 1
    now = clock_from(config)
    signal["retry"] = {
        "attempts": attempts, "reason": report.get("reason", report["status"]),
        "first_failed_at": previous.get("first_failed_at", now.isoformat()),
        "last_failed_at": now.isoformat(),
        "next_attempt_at": (now + timedelta(seconds=30 * 2 ** (attempts - 1))).isoformat(),
    }
    atomic_write_json(path, signal)
    if attempts >= 3:
        _dead_letter_wake(repo_root, path, signal, now=now)
        report["dead_lettered"] = True


def _dead_letter_wake(repo_root: Path, path: Path, signal: dict[str, Any], *, now: datetime) -> None:
    destination = repo_root / "runtime/dispatch/wake_queue/dead_letter" / path.parent.name / path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    signal["retry"]["dead_lettered_at"] = now.isoformat()
    atomic_write_json(destination, signal)
    _exhaust_assignment(repo_root, str(signal.get('assignment_id', '')),
                        'wake dead-lettered after automatic retries exhausted: ' + str(signal['retry'].get('reason', 'unknown')))
    path.unlink()


def process_once(repo_root: Path, *, config: SupervisorConfig | None = None, **kwargs: Any) -> dict[str, Any]:
    cfg = config or SupervisorConfig()
    _update_status(repo_root, **root_metadata(repo_root))
    recover_orphans(repo_root, config=cfg)
    from orchestrator.stuck_assignments import recover_stuck_assignments
    recover_stuck_assignments(repo_root, max_automatic_retry=cfg.max_automatic_retry)
    # Re-evaluate every tick, before waking new work, so due retries cannot starve.
    report = reevaluate_blocked_builders(
        repo_root, config=cfg, launch=process_wake_signal, single_launch=True, **kwargs
    )
    if report is not None and report.get("process_started"):
        return report
    queue = _wake_queue(repo_root, cfg.agent)
    signals = sorted(queue.glob("*.json")) if queue.is_dir() else []
    for path in signals:
        try:
            data = read_wake_signal(path)
            retry = data.get("retry", {}) if isinstance(data, dict) else {}
            if isinstance(retry, dict) and int(retry.get("attempts", 0)) >= 3:
                # Complete an interrupted dead-letter move without a fourth launch.
                _dead_letter_wake(repo_root, path, data, now=clock_from(cfg))
                report = {"status": "error", "reason": retry.get("reason"), "dead_lettered": True}
                continue
            due = retry.get("next_attempt_at") if isinstance(retry, dict) else None
            if due and clock_from(cfg) < datetime.fromisoformat(due):
                continue
        except (ValueError, TypeError):
            pass  # Malformed JSON is a bounded failure too.
        current = process_wake_signal(repo_root, path, config=cfg, single_launch=True, **kwargs)
        if current.get("status") in {"error", "failed_launch", "blocked"} and path.exists():
            _retry_wake(repo_root, path, current, config=cfg)
        report = current
        if current.get("process_started") or current.get("pid"):
            break
    alerts = []
    for path in sorted((repo_root / "runtime/dispatch/wake_queue/dead_letter").rglob("*.json")):
        alerts.append({"path": str(path.relative_to(repo_root)), "retry": read_wake_signal(path).get("retry")})
    _update_status(repo_root, wake_alerts=alerts)
    return report or {"status": "idle", "agent": cfg.agent}


def run_forever(
    repo_root: Path, *, config: SupervisorConfig | None = None,
    state_logger: Callable[[dict[str, Any]], None] | None = None, **kwargs: Any,
) -> int:
    cfg = config or SupervisorConfig()
    global STOP_REQUESTED
    STOP_REQUESTED = False
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_stop)

    status_path = repo_root / "runtime" / "dispatch" / "supervisor_status.json"
    status: dict[str, Any] = {"idle_ticks": 0, "last_state": None}
    if status_path.is_file():
        try:
            loaded = json.loads(status_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                status.update(loaded)
        except (OSError, json.JSONDecodeError):
            pass

    status.update(root_metadata(repo_root))
    atomic_write_json(status_path, status)

    while not STOP_REQUESTED:
        layer_heartbeat.tick()
        report = process_once(repo_root, config=cfg, **kwargs)
        report_status = str(report.get("status"))
        if report_status == "idle":
            status["idle_ticks"] = int(status.get("idle_ticks", 0)) + 1
        state_key = json.dumps(report, sort_keys=True, default=str)
        if report_status != "idle" and state_key != status.get("last_state") and state_logger:
            state_logger(report)
        status.update({"last_tick_at": utc_now(), "last_state": state_key})
        status["quota_probes"] = paid_probe_status(repo_root, now=clock_from(cfg))
        status["quota_probe_alerts"] = {
            provider: {"classification": "probe_misconfigured", "reason": details["alert_reason"]}
            for provider, details in status["quota_probes"].items() if "alert_reason" in details
        }
        status_path.parent.mkdir(parents=True, exist_ok=True)
        _update_status(repo_root, **{k: v for k, v in status.items()
                                   if k not in {"wake_alerts", "work_lock_alerts"}})
        if report.get("status") == "idle":
            time.sleep(max(1, cfg.poll_seconds))
        else:
            time.sleep(max(1, min(cfg.poll_seconds, 2)))
    return 0
