"""File-based Claude ↔ Composer assignment channel (inbox/outbox). Read-only ingestion safe."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

ASSIGNMENT_SCHEMA_VERSION = "1.0"
INBOX_DIRNAME = "inbox"
OUTBOX_DIRNAME = "outbox"

AssignmentStatus = Literal["pending", "claimed", "cancelled"]
OutboxStatus = Literal["completed", "failed", "blocked"]

REQUIRED_INBOX_FIELDS = frozenset(
    {
        "schema_version",
        "assignment_id",
        "task_id",
        "adapter_id",
        "assigned_by",
        "assigned_to",
        "status",
        "created_at",
        "execution_route",
        "task_path",
        "handoff_rel",
    }
)

REQUIRED_OUTBOX_FIELDS = frozenset(
    {
        "schema_version",
        "assignment_id",
        "task_id",
        "adapter_id",
        "status",
        "finished_at",
    }
)

VALID_INBOX_STATUSES = frozenset({"pending", "claimed", "cancelled"})
VALID_OUTBOX_STATUSES = frozenset({"completed", "failed", "blocked"})


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def assignments_root(repo_root: Path) -> Path:
    return repo_root / "runtime" / "dispatch" / "assignments"


def inbox_dir(repo_root: Path) -> Path:
    return assignments_root(repo_root) / INBOX_DIRNAME


def outbox_dir(repo_root: Path) -> Path:
    return assignments_root(repo_root) / OUTBOX_DIRNAME


def generate_assignment_id(task_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:8]
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", task_id.strip()).strip("-")[:24]
    return f"assign-{stamp}-{safe}-{suffix}"


@dataclass
class AssignmentRecord:
    assignment_id: str
    task_id: str
    adapter_id: str
    assigned_by: str
    assigned_to: str
    status: str
    created_at: str
    updated_at: str
    execution_route: str
    task_path: str
    handoff_rel: str
    base_sha: str | None = None
    allowed_paths: list[str] = field(default_factory=list)
    instructions: str | None = None
    parse_errors: list[str] = field(default_factory=list)
    source_path: str = ""


@dataclass
class OutboxRecord:
    assignment_id: str
    task_id: str
    adapter_id: str
    status: str
    finished_at: str
    run_id: str | None = None
    handoff_path: str | None = None
    branch_tip_sha: str | None = None
    blocked_reasons: list[str] = field(default_factory=list)
    result_summary: str | None = None
    parse_errors: list[str] = field(default_factory=list)
    source_path: str = ""


def _load_json_file(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    if not path.is_file():
        return None, [f"{path}: file does not exist"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"{path}: malformed JSON: {exc}"]
    if not isinstance(data, dict):
        return None, [f"{path}: root must be a JSON object"]
    return data, errors


def validate_inbox_payload(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_INBOX_FIELDS - set(data))
    if missing:
        errors.append(f"missing required fields: {', '.join(missing)}")
    if str(data.get("schema_version", "")) != ASSIGNMENT_SCHEMA_VERSION:
        errors.append(f"schema_version must be {ASSIGNMENT_SCHEMA_VERSION!r}")
    status = str(data.get("status", ""))
    if status and status not in VALID_INBOX_STATUSES:
        errors.append(f"invalid inbox status: {status!r}")
    if data.get("adapter_id") and str(data["adapter_id"]) != "composer-restricted":
        errors.append("Phase 3.8 inbox adapter_id must be composer-restricted")
    if data.get("execution_route") and str(data["execution_route"]) != "composer_local_builder":
        errors.append("execution_route must be composer_local_builder")
    return errors


def validate_outbox_payload(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_OUTBOX_FIELDS - set(data))
    if missing:
        errors.append(f"missing required fields: {', '.join(missing)}")
    if str(data.get("schema_version", "")) != ASSIGNMENT_SCHEMA_VERSION:
        errors.append(f"schema_version must be {ASSIGNMENT_SCHEMA_VERSION!r}")
    status = str(data.get("status", ""))
    if status and status not in VALID_OUTBOX_STATUSES:
        errors.append(f"invalid outbox status: {status!r}")
    return errors


def parse_assignment_record(data: dict[str, Any], *, source_path: str = "") -> AssignmentRecord:
    errors = validate_inbox_payload(data)
    allowed = data.get("allowed_paths")
    return AssignmentRecord(
        assignment_id=str(data.get("assignment_id") or ""),
        task_id=str(data.get("task_id") or ""),
        adapter_id=str(data.get("adapter_id") or ""),
        assigned_by=str(data.get("assigned_by") or ""),
        assigned_to=str(data.get("assigned_to") or ""),
        status=str(data.get("status") or "unknown"),
        created_at=str(data.get("created_at") or ""),
        updated_at=str(data.get("updated_at") or data.get("created_at") or ""),
        execution_route=str(data.get("execution_route") or ""),
        task_path=str(data.get("task_path") or ""),
        handoff_rel=str(data.get("handoff_rel") or ""),
        base_sha=str(data.get("base_sha") or "") or None,
        allowed_paths=list(allowed) if isinstance(allowed, list) else [],
        instructions=str(data.get("instructions") or "") or None,
        parse_errors=errors,
        source_path=source_path,
    )


def parse_outbox_record(data: dict[str, Any], *, source_path: str = "") -> OutboxRecord:
    errors = validate_outbox_payload(data)
    blocked = data.get("blocked_reasons")
    return OutboxRecord(
        assignment_id=str(data.get("assignment_id") or ""),
        task_id=str(data.get("task_id") or ""),
        adapter_id=str(data.get("adapter_id") or ""),
        status=str(data.get("status") or "unknown"),
        finished_at=str(data.get("finished_at") or ""),
        run_id=str(data.get("run_id") or "") or None,
        handoff_path=str(data.get("handoff_path") or "") or None,
        branch_tip_sha=str(data.get("branch_tip_sha") or "") or None,
        blocked_reasons=list(blocked) if isinstance(blocked, list) else [],
        result_summary=str(data.get("result_summary") or "") or None,
        parse_errors=errors,
        source_path=source_path,
    )


def write_assignment(
    repo_root: Path,
    *,
    task_id: str,
    task_path: str,
    assigned_by: str = "claude",
    assigned_to: str = "composer",
    base_sha: str | None = None,
    allowed_paths: list[str] | None = None,
    instructions: str | None = None,
    assignment_id: str | None = None,
) -> tuple[Path | None, list[str]]:
    """Write a pending assignment to inbox. Does not execute Composer."""
    errors: list[str] = []
    aid = assignment_id or generate_assignment_id(task_id)
    now = utc_now()
    handoff_rel = f"handoffs/{task_id}__composer__to__claude.md"
    payload = {
        "schema_version": ASSIGNMENT_SCHEMA_VERSION,
        "assignment_id": aid,
        "task_id": task_id,
        "adapter_id": "composer-restricted",
        "assigned_by": assigned_by,
        "assigned_to": assigned_to,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "execution_route": "composer_local_builder",
        "task_path": task_path,
        "base_sha": base_sha,
        "allowed_paths": allowed_paths or [],
        "instructions": instructions,
        "handoff_rel": handoff_rel,
    }
    errors.extend(validate_inbox_payload(payload))
    if errors:
        return None, errors

    target = inbox_dir(repo_root) / f"{aid}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target, []


def read_assignment(repo_root: Path, assignment_id: str) -> tuple[AssignmentRecord | None, list[str]]:
    path = inbox_dir(repo_root) / f"{assignment_id}.json"
    data, errors = _load_json_file(path)
    if data is None:
        return None, errors
    record = parse_assignment_record(data, source_path=str(path.relative_to(repo_root)))
    errors.extend(record.parse_errors)
    return record, errors


def list_inbox_assignments(repo_root: Path) -> tuple[list[AssignmentRecord], list[str]]:
    root = inbox_dir(repo_root)
    if not root.exists():
        return [], []
    if not root.is_dir():
        return [], [f"{root}: path exists but is not a directory"]

    records: list[AssignmentRecord] = []
    errors: list[str] = []
    for path in sorted(root.glob("*.json")):
        data, load_errors = _load_json_file(path)
        errors.extend(load_errors)
        if data is None:
            records.append(
                AssignmentRecord(
                    assignment_id=path.stem,
                    task_id="",
                    adapter_id="",
                    assigned_by="",
                    assigned_to="",
                    status="unknown",
                    created_at="",
                    updated_at="",
                    execution_route="",
                    task_path="",
                    handoff_rel="",
                    parse_errors=load_errors,
                    source_path=str(path.relative_to(repo_root)),
                )
            )
            continue
        record = parse_assignment_record(data, source_path=str(path.relative_to(repo_root)))
        errors.extend(record.parse_errors)
        records.append(record)
    return records, errors


def read_outbox_result(repo_root: Path, assignment_id: str) -> tuple[OutboxRecord | None, list[str]]:
    path = outbox_dir(repo_root) / f"{assignment_id}.json"
    data, errors = _load_json_file(path)
    if data is None:
        return None, errors
    record = parse_outbox_record(data, source_path=str(path.relative_to(repo_root)))
    errors.extend(record.parse_errors)
    return record, errors


def list_outbox_results(repo_root: Path) -> tuple[list[OutboxRecord], list[str]]:
    root = outbox_dir(repo_root)
    if not root.exists():
        return [], []
    if not root.is_dir():
        return [], [f"{root}: path exists but is not a directory"]

    records: list[OutboxRecord] = []
    errors: list[str] = []
    for path in sorted(root.glob("*.json")):
        data, load_errors = _load_json_file(path)
        errors.extend(load_errors)
        if data is None:
            records.append(
                OutboxRecord(
                    assignment_id=path.stem,
                    task_id="",
                    adapter_id="",
                    status="unknown",
                    finished_at="",
                    parse_errors=load_errors,
                    source_path=str(path.relative_to(repo_root)),
                )
            )
            continue
        record = parse_outbox_record(data, source_path=str(path.relative_to(repo_root)))
        errors.extend(record.parse_errors)
        records.append(record)
    return records, errors


def ingest_handoff_from_outbox(repo_root: Path, assignment_id: str) -> tuple[str | None, list[str]]:
    """Read-only: resolve handoff path from outbox record if present."""
    record, errors = read_outbox_result(repo_root, assignment_id)
    if record is None:
        return None, errors
    if record.handoff_path:
        return record.handoff_path, errors
    if errors:
        return None, errors
    return None, [f"outbox {assignment_id}: handoff_path not set"]