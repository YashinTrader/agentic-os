"""Normalize Codex CLI outputs into agent execution result contract."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

CompletionStatus = Literal[
    "blocked",
    "started",
    "completed_unverified",
    "completed_verified",
    "failed",
    "timed_out",
    "handoff_missing",
]


@dataclass
class AgentExecutionResult:
    run_id: str
    task_id: str
    adapter_id: str
    process_exit_code: int | None
    timed_out: bool
    started_at: str
    finished_at: str
    duration_ms: int
    stdout_path: str
    stderr_path: str
    agent_output_path: str
    files_changed: list[str] = field(default_factory=list)
    git_diff_stat: str = ""
    verification_commands: list[str] = field(default_factory=list)
    verification_results: list[dict[str, Any]] = field(default_factory=list)
    handoff_path: str = ""
    blocked_reasons: list[str] = field(default_factory=list)
    error: str = ""
    completion_status: CompletionStatus = "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "adapter_id": self.adapter_id,
            "process_exit_code": self.process_exit_code,
            "timed_out": self.timed_out,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "agent_output_path": self.agent_output_path,
            "files_changed": list(self.files_changed),
            "git_diff_stat": self.git_diff_stat,
            "verification_commands": list(self.verification_commands),
            "verification_results": list(self.verification_results),
            "handoff_path": self.handoff_path,
            "blocked_reasons": list(self.blocked_reasons),
            "error": self.error,
            "completion_status": self.completion_status,
        }


def _parse_iso_duration_ms(started: str, finished: str) -> int:
    try:
        s = datetime.fromisoformat(started.replace("Z", "+00:00"))
        f = datetime.fromisoformat(finished.replace("Z", "+00:00"))
        return max(0, int((f - s).total_seconds() * 1000))
    except ValueError:
        return 0


def parse_codex_jsonl_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def parse_agent_execution_result(
    *,
    run_id: str,
    task_id: str,
    adapter_id: str,
    process_exit_code: int | None,
    timed_out: bool,
    started_at: str,
    finished_at: str,
    stdout_path: str,
    stderr_path: str,
    agent_output_path: str,
    handoff_path: str = "",
    git_diff_stat: str = "",
    files_changed: list[str] | None = None,
    verification_commands: list[str] | None = None,
    verification_results: list[dict[str, Any]] | None = None,
    blocked_reasons: list[str] | None = None,
    error: str = "",
) -> AgentExecutionResult:
    """Derive completion_status — exit code 0 alone is insufficient."""
    blocked = list(blocked_reasons or [])
    ver_results = list(verification_results or [])
    ver_cmds = list(verification_commands or [])
    changed = list(files_changed or [])

    if blocked:
        status: CompletionStatus = "blocked"
    elif timed_out:
        status = "timed_out"
    elif process_exit_code not in (0, None) and process_exit_code != 0:
        status = "failed"
    elif not handoff_path or not Path(handoff_path).exists():
        status = "handoff_missing"
    elif not ver_cmds or not ver_results:
        status = "completed_unverified"
    elif any(r.get("exit_code", 1) != 0 for r in ver_results):
        status = "completed_unverified"
    elif not git_diff_stat and not changed:
        status = "completed_unverified"
    else:
        status = "completed_verified"

    return AgentExecutionResult(
        run_id=run_id,
        task_id=task_id,
        adapter_id=adapter_id,
        process_exit_code=process_exit_code,
        timed_out=timed_out,
        started_at=started_at,
        finished_at=finished_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        duration_ms=_parse_iso_duration_ms(started_at, finished_at),
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        agent_output_path=agent_output_path,
        files_changed=changed,
        git_diff_stat=git_diff_stat,
        verification_commands=ver_cmds,
        verification_results=ver_results,
        handoff_path=handoff_path,
        blocked_reasons=blocked,
        error=error,
        completion_status=status,
    )