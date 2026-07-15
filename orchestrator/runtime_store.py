"""Durable supervisor run-state under runtime/dispatch/runs/."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dispatch.atomic_io import atomic_write_json
from dispatch.runtime_capture import run_directory

# Truthful process states for physical launches.
STATE_QUEUED = "queued"
STATE_LAUNCHING = "launching"
STATE_RUNNING = "running"
STATE_COMPLETED = "completed"
STATE_BLOCKED_AUTHENTICATION = "blocked_authentication"
STATE_BLOCKED_QUOTA = "blocked_quota"
STATE_BLOCKED_NO_ADAPTER = "blocked_no_adapter"
STATE_BLOCKED_CAPACITY = "blocked_capacity"
STATE_FAILED_LAUNCH = "failed_launch"
STATE_FAILED = "failed"
STATE_TIMED_OUT = "timed_out"
STATE_ORPHANED = "orphaned"

TERMINAL_STATES = frozenset(
    {
        STATE_COMPLETED,
        STATE_BLOCKED_AUTHENTICATION,
        STATE_BLOCKED_QUOTA,
        STATE_BLOCKED_NO_ADAPTER,
        STATE_BLOCKED_CAPACITY,
        STATE_FAILED_LAUNCH,
        STATE_FAILED,
        STATE_TIMED_OUT,
        STATE_ORPHANED,
    }
)

BLOCKED_EXTERNAL_STATES = frozenset(
    {
        STATE_BLOCKED_AUTHENTICATION,
        STATE_BLOCKED_QUOTA,
        STATE_BLOCKED_NO_ADAPTER,
        STATE_BLOCKED_CAPACITY,
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class FailureFingerprint:
    agent: str
    adapter: str
    failure_category: str
    cli_exit_code: int | None = None
    normalized_error_type: str = ""
    retry_after: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def unchanged(self, other: "FailureFingerprint | None") -> bool:
        if other is None:
            return False
        return (
            self.agent == other.agent
            and self.adapter == other.adapter
            and self.failure_category == other.failure_category
            and self.cli_exit_code == other.cli_exit_code
            and self.normalized_error_type == other.normalized_error_type
            and (self.retry_after or "") == (other.retry_after or "")
        )


@dataclass
class RunState:
    run_id: str
    assignment_id: str
    task_id: str
    assigned_agent: str
    adapter: str
    process_state: str = STATE_QUEUED
    pid: int | None = None
    session_id: str | None = None
    worktree: str = ""
    branch: str = ""
    base_sha: str = ""
    executable: str = ""
    executable_version: str = ""
    command_redacted: list[str] = field(default_factory=list)
    started_at: str | None = None
    heartbeat_at: str | None = None
    completed_at: str | None = None
    exit_code: int | None = None
    stdout_path: str = ""
    stderr_path: str = ""
    handoff_path: str = ""
    blocked_reason: str = ""
    retry_eligible: bool = False
    retry_count: int = 0
    failure_fingerprint: dict[str, Any] | None = None
    fallback_from_run_id: str | None = None
    fallback_to_agent: str | None = None
    wake_signal_path: str = ""
    schema_version: str = "1.0"
    kind: str = "physical_agent_launch"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_state_path(run_dir: Path) -> Path:
    return run_dir / "supervisor_run.json"


def result_path(run_dir: Path) -> Path:
    return run_dir / "result.json"


def save_run_state(repo_root: Path, state: RunState) -> Path:
    run_dir = run_directory(repo_root, state.run_id)
    path = run_state_path(run_dir)
    atomic_write_json(path, state.to_dict())
    # Mirror key fields into result.json for dashboard compatibility.
    atomic_write_json(
        result_path(run_dir),
        {
            "run_id": state.run_id,
            "assignment_id": state.assignment_id,
            "task_id": state.task_id,
            "status": state.process_state,
            "process_state": state.process_state,
            "assigned_agent": state.assigned_agent,
            "adapter_id": state.adapter,
            "pid": state.pid,
            "session_id": state.session_id,
            "worktree_path": state.worktree,
            "branch": state.branch,
            "base_sha": state.base_sha,
            "started_at": state.started_at,
            "heartbeat_at": state.heartbeat_at,
            "finished_at": state.completed_at,
            "exit_code": state.exit_code,
            "stdout_path": state.stdout_path,
            "stderr_path": state.stderr_path,
            "handoff_path": state.handoff_path,
            "blocked_reasons": [state.blocked_reason] if state.blocked_reason else [],
            "blocked_reason": state.blocked_reason,
            "retry_eligible": state.retry_eligible,
            "retry_count": state.retry_count,
            "failure_fingerprint": state.failure_fingerprint,
            "fallback_from_run_id": state.fallback_from_run_id,
            "fallback_to_agent": state.fallback_to_agent,
            "kind": state.kind,
            "command_redacted": state.command_redacted,
            "executable": state.executable,
            "executable_version": state.executable_version,
        },
    )
    return path


def load_run_state(repo_root: Path, run_id: str) -> RunState | None:
    path = run_state_path(run_directory(repo_root, run_id))
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    known = {f.name for f in RunState.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    filtered = {k: v for k, v in data.items() if k in known}
    try:
        return RunState(**filtered)
    except TypeError:
        return None


def list_supervisor_runs(repo_root: Path, *, limit: int = 50) -> list[RunState]:
    runs_root = repo_root / "runtime" / "dispatch" / "runs"
    if not runs_root.is_dir():
        return []
    states: list[RunState] = []
    for path in sorted(runs_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_dir():
            continue
        state = load_run_state(repo_root, path.name)
        if state is not None:
            states.append(state)
        if len(states) >= limit:
            break
    return states


def find_latest_run_for_assignment(repo_root: Path, assignment_id: str) -> RunState | None:
    for state in list_supervisor_runs(repo_root, limit=200):
        if state.assignment_id == assignment_id:
            return state
    return None
