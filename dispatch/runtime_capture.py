"""Phase 3.2 execution runtime capture — artifacts under runtime/dispatch/runs/."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ExecutionResult:
    run_id: str
    task_id: str
    adapter_id: str
    executed: bool
    execution_allowed: bool
    approval_level: str
    approval_status: str
    exit_code: int | None = None
    timed_out: bool = False
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    stdout_path: str = ""
    stderr_path: str = ""
    result_path: str = ""
    blocked_reasons: list[str] = field(default_factory=list)
    error: str | None = None
    handoff_path: str = ""
    rollback_path: str = ""


def run_directory(repo_root: Path, run_id: str) -> Path:
    path = repo_root / "runtime" / "dispatch" / "runs" / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_execution_request(run_dir: Path, request: dict[str, Any]) -> Path:
    path = run_dir / "execution_request.json"
    write_json(path, request)
    return path


def write_preview_copy(run_dir: Path, preview: dict[str, Any]) -> Path:
    path = run_dir / "preview.json"
    write_json(path, preview)
    return path


def write_approval_copy(run_dir: Path, approval: dict[str, Any]) -> Path:
    path = run_dir / "approval_record.json"
    write_json(path, approval)
    return path


def write_result(run_dir: Path, result: ExecutionResult) -> Path:
    path = run_dir / "result.json"
    payload = asdict(result)
    write_json(path, payload)
    return path


def append_run_event(run_dir: Path, event: dict[str, Any]) -> Path:
    path = run_dir / "events.jsonl"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n")
    return path


def write_rollback_md(run_dir: Path, notes: str) -> Path:
    path = run_dir / "rollback.md"
    body = notes.strip() or "No rollback steps required for read-only execution."
    path.write_text(body + "\n", encoding="utf-8")
    return path


def write_handoff_required_md(run_dir: Path, handoff_path: str) -> Path:
    path = run_dir / "handoff_required.md"
    body = (
        f"# Handoff required\n\n"
        f"Execution completed or was blocked. Operator must write handoff at:\n\n"
        f"`{handoff_path}`\n"
    )
    path.write_text(body, encoding="utf-8")
    return path


def persist_latest_pointers(repo_root: Path, run_id: str, result: ExecutionResult) -> None:
    """Update latest execution pointers for dashboard read-only display."""
    dispatch_dir = repo_root / "runtime" / "dispatch"
    dispatch_dir.mkdir(parents=True, exist_ok=True)
    latest_result = dispatch_dir / "latest_result.json"
    write_json(latest_result, asdict(result))
    latest_run = dispatch_dir / "latest_run_id.txt"
    latest_run.write_text(run_id + "\n", encoding="utf-8")