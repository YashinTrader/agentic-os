"""Monitor launched agent processes: heartbeat, completion, orphan recovery."""

from __future__ import annotations

import os
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from orchestrator.layer_heartbeat import tick
from orchestrator.process_ownership import terminate_owned, pid_is_alive
from orchestrator.run_deadlines import (
    DeadlinePolicy, RunDeadlines, StreamActivity, adapter_deadlines, worktree_snapshot,
)
from orchestrator.runtime_store import (
    STATE_ORPHANED,
    STATE_RUNNING,
    STATE_TIMED_OUT,
    RunState,
    save_run_state,
    utc_now,
)

PollFn = Callable[[Any], int | None]


@dataclass
class MonitorResult:
    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str
    orphaned: bool = False
    deadline_state: str | None = None


def _default_poll(process: Any) -> int | None:
    return process.poll()


def _default_wait(process: Any, timeout: float | None) -> int:
    return int(process.wait(timeout=timeout))


def read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def monitor_process(
    process: Any,
    *,
    state: RunState,
    repo_root: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
    heartbeat_seconds: float = 2.0,
    poll_fn: PollFn | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    kill_fn: Callable[[Any], None] | None = None,
    clock_fn: Callable[[], float] | None = None,
    deadline_policy: DeadlinePolicy | None = None,
    persist_fn: Callable[..., Any] | None = None,
    worktree: Path | None = None,
    initial_snapshot: dict | None = None,
    started_monotonic: float | None = None,
) -> MonitorResult:
    """Block until process exits or times out; keep heartbeat fresh.

    State must already be `running` with a real PID recorded before calling.
    """
    if state.process_state != STATE_RUNNING or not state.pid:
        raise ValueError("monitor_process requires running state with PID")

    poll = poll_fn or _default_poll
    sleep = sleep_fn or time.sleep
    clock = clock_fn or time.monotonic
    started = clock() if started_monotonic is None else started_monotonic
    policy = deadline_policy or adapter_deadlines(repo_root, state.adapter, timeout_seconds)
    deadlines = RunDeadlines(policy, started)
    persist_state = persist_fn or save_run_state
    last_warning = None

    def persist(root: Path, current: RunState) -> None:
        nonlocal last_warning
        try:
            persist_state(root, current)
        except OSError as exc:
            # Keep process ownership and in-memory activity until exit. The next
            # poll retries; final classification is persisted by the supervisor.
            now = clock()
            if last_warning is None or now - last_warning >= 60:
                logging.getLogger(__name__).warning('Run %s persistence deferred: %.300s', current.run_id, exc)
                last_warning = now
    grok_stream = getattr(state, "adapter", "") == "composer-restricted"
    activity = StreamActivity(stdout_path, grok_stream=grok_stream)
    if worktree is None and getattr(state, "worktree", ""):
        worktree = Path(state.worktree)
    excluded = (stdout_path, stderr_path)
    snapshot = initial_snapshot if initial_snapshot is not None else worktree_snapshot(worktree, excluded)
    exit_code: int | None = None
    timed_out = False
    deadline_state = None

    try:
        while True:
            tick()
            code = poll(process)
            now = clock()
            fired = deadlines.expired(now)
            events = activity.poll()
            if grok_stream:
                state.liveness_events = activity.liveness_events
            current = worktree_snapshot(worktree, excluded)
            events += sum(snapshot.get(path) != value for path, value in current.items())
            snapshot = current
            if events and fired is None:
                deadlines.activity(now, state, utc_now(), events)
            state.heartbeat_at = utc_now()
            persist(repo_root, state)
            if code is not None and fired is None:
                exit_code = int(code)
                terminate_owned(process)
                break
            if fired:
                state.deadline_fired, deadline_state = fired
                state.deadline_fired_at = utc_now()
                state.completed_at = state.deadline_fired_at
                state.process_state = deadline_state
                state.blocked_reason = f"{state.deadline_fired} deadline expired"
                persist(repo_root, state)
                timed_out = deadline_state == "timed_out"
                if kill_fn is not None:
                    kill_fn(process)
                else:
                    try:
                        terminate_owned(process)
                    except OSError:
                        pass
                    try:
                        exit_code = int(process.wait(timeout=5))
                    except Exception:
                        exit_code = None
                break
            sleep(max(0.05, heartbeat_seconds))
    except BaseException:
        if process.poll() is None:
            terminate_owned(process)
            process.wait(timeout=5)
        raise

    return MonitorResult(
        exit_code=exit_code,
        timed_out=timed_out,
        stdout=read_text(stdout_path),
        stderr=read_text(stderr_path),
        orphaned=False,
        deadline_state=deadline_state,
    )


def classify_orphan(state: RunState, *, process_alive: bool | None) -> str | None:
    """Return orphaned state if a run looks abandoned."""
    if state.process_state not in {STATE_RUNNING, "launching"}:
        return None
    if process_alive is False:
        return STATE_ORPHANED
    if state.pid and process_alive is None:
        # Unknown liveness — leave running, but surface orphaned only when proven dead.
        return None
    return None


def mark_orphaned(repo_root: Path, state: RunState, *, detail: str = "process missing") -> RunState:
    state.process_state = STATE_ORPHANED
    state.completed_at = utc_now()
    state.blocked_reason = detail
    state.retry_eligible = False
    # Dead-run evidence must remain recordable even after explicit supersede.
    # This does not authorize completion or mutate a replacement's work lock.
    save_run_state(repo_root, state, refresh_work_lock=False)
    return state
