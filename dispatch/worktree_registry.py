"""Worktree allocation registry — file-based, no database."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from dispatch.atomic_io import atomic_write_json

ALLOCATION_STATUSES = frozenset(
    {
        "requested",
        "allocated",
        "active",
        "completed",
        "failed",
        "preserved",
        "cleanup_pending",
        "cleaned",
    }
)

ACTIVE_STATUSES = frozenset({"requested", "allocated", "active", "cleanup_pending"})

AllocationStatus = Literal[
    "requested",
    "allocated",
    "active",
    "completed",
    "failed",
    "preserved",
    "cleanup_pending",
    "cleaned",
]


@dataclass
class AllocationRecord:
    allocation_id: str
    run_id: str
    task_id: str
    repo_root: str
    worktree_root: str
    worktree_path: str
    branch_name: str
    base_sha: str
    base_branch: str
    created_at: str
    expires_at: str
    status: str
    cleanup_policy: str
    writes_files: bool
    owner: str
    last_verified_at: str
    dirty: bool
    git_head: str
    error: str = ""
    audit: list[dict[str, str]] = field(default_factory=list)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_allocation_id() -> str:
    return f"alloc-{uuid4().hex}"


def _allocations_dir(repo_root: Path) -> Path:
    return repo_root / "runtime" / "worktrees" / "allocations"


def allocation_record_to_dict(record: AllocationRecord) -> dict[str, Any]:
    data = asdict(record)
    return data


def allocation_record_from_dict(data: dict[str, Any]) -> AllocationRecord:
    audit = data.get("audit") or []
    if not isinstance(audit, list):
        audit = []
    return AllocationRecord(
        allocation_id=str(data["allocation_id"]),
        run_id=str(data["run_id"]),
        task_id=str(data["task_id"]),
        repo_root=str(data["repo_root"]),
        worktree_root=str(data["worktree_root"]),
        worktree_path=str(data["worktree_path"]),
        branch_name=str(data["branch_name"]),
        base_sha=str(data["base_sha"]),
        base_branch=str(data.get("base_branch", "")),
        created_at=str(data["created_at"]),
        expires_at=str(data.get("expires_at", "")),
        status=str(data["status"]),
        cleanup_policy=str(data.get("cleanup_policy", "manual")),
        writes_files=bool(data.get("writes_files", True)),
        owner=str(data.get("owner", "operator")),
        last_verified_at=str(data.get("last_verified_at", "")),
        dirty=bool(data.get("dirty", False)),
        git_head=str(data.get("git_head", "")),
        error=str(data.get("error", "")),
        audit=[dict(entry) for entry in audit if isinstance(entry, dict)],
    )


def validate_allocation_id(allocation_id: str) -> None:
    if not re.fullmatch(r"alloc-[0-9a-f]{32}", allocation_id):
        raise ValueError(f"invalid allocation_id: {allocation_id!r}")


def save_allocation_record(repo_root: Path, record: AllocationRecord) -> Path:
    validate_allocation_id(record.allocation_id)
    if record.status not in ALLOCATION_STATUSES:
        raise ValueError(f"invalid allocation status: {record.status!r}")
    path = _allocations_dir(repo_root) / f"{record.allocation_id}.json"
    atomic_write_json(path, allocation_record_to_dict(record))
    return path


def load_allocation_record(repo_root: Path, allocation_id: str) -> AllocationRecord:
    validate_allocation_id(allocation_id)
    path = _allocations_dir(repo_root) / f"{allocation_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("allocation record must be a JSON object")
    return allocation_record_from_dict(data)


def load_allocation_by_path(repo_root: Path, path: Path) -> AllocationRecord:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("allocation record must be a JSON object")
    return allocation_record_from_dict(data)


def list_allocation_records(repo_root: Path) -> list[AllocationRecord]:
    directory = _allocations_dir(repo_root)
    if not directory.exists():
        return []
    records: list[AllocationRecord] = []
    for path in sorted(directory.glob("alloc-*.json")):
        try:
            records.append(load_allocation_by_path(repo_root, path))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return records


def find_by_run_id(repo_root: Path, run_id: str) -> AllocationRecord | None:
    for record in list_allocation_records(repo_root):
        if record.run_id == run_id and record.status in ACTIVE_STATUSES:
            return record
    return None


def find_by_worktree_path(repo_root: Path, worktree_path: str) -> AllocationRecord | None:
    target = str(Path(worktree_path).resolve())
    for record in list_allocation_records(repo_root):
        if str(Path(record.worktree_path).resolve()) == target and record.status in ACTIVE_STATUSES:
            return record
    return None


def transition_status(
    repo_root: Path,
    allocation_id: str,
    new_status: str,
    *,
    error: str = "",
    dirty: bool | None = None,
    git_head: str | None = None,
) -> AllocationRecord:
    if new_status not in ALLOCATION_STATUSES:
        raise ValueError(f"invalid status transition target: {new_status!r}")
    record = load_allocation_record(repo_root, allocation_id)
    updated = AllocationRecord(
        allocation_id=record.allocation_id,
        run_id=record.run_id,
        task_id=record.task_id,
        repo_root=record.repo_root,
        worktree_root=record.worktree_root,
        worktree_path=record.worktree_path,
        branch_name=record.branch_name,
        base_sha=record.base_sha,
        base_branch=record.base_branch,
        created_at=record.created_at,
        expires_at=record.expires_at,
        status=new_status,
        cleanup_policy=record.cleanup_policy,
        writes_files=record.writes_files,
        owner=record.owner,
        last_verified_at=utc_now(),
        dirty=record.dirty if dirty is None else dirty,
        git_head=record.git_head if git_head is None else git_head,
        error=error or record.error,
        audit=list(record.audit)
        + [{"at": utc_now(), "from": record.status, "to": new_status, "error": error}],
    )
    save_allocation_record(repo_root, updated)
    return updated


def assert_no_active_duplicate(
    repo_root: Path,
    *,
    run_id: str,
    branch_name: str,
    worktree_path: str,
) -> list[str]:
    """Return blocking reasons if an active allocation conflicts."""
    reasons: list[str] = []
    resolved_path = str(Path(worktree_path).resolve())
    for record in list_allocation_records(repo_root):
        if record.status not in ACTIVE_STATUSES:
            continue
        if record.run_id == run_id:
            reasons.append(f"active allocation already exists for run_id {run_id!r}")
        if record.branch_name == branch_name:
            reasons.append(f"branch {branch_name!r} already allocated")
        if str(Path(record.worktree_path).resolve()) == resolved_path:
            reasons.append(f"worktree path {worktree_path!r} already allocated")
    return reasons