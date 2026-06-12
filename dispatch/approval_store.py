"""Phase 3.2 approval record persistence — create and load only, no execution."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from dispatch.approval_contract import (
    ApprovalRecord,
    approval_record_to_dict,
    default_approval_expires_at,
    validate_approval_record_shape,
)
from dispatch.freshness import compute_preview_hash


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_approval_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"approval-{stamp}-{uuid4().hex[:8]}"


def command_hash(command: str) -> str:
    return hashlib.sha256(command.encode("utf-8")).hexdigest()


def build_approval_record(
    preview: dict[str, Any],
    *,
    approval_level: str,
    approved_by: str,
    approver_type: str,
    ttl_minutes: int | None = None,
    notes: str = "",
    adapter: dict[str, Any] | None = None,
) -> ApprovalRecord:
    """Build a new approval record tied to preview hash and command."""
    run_id = str(preview.get("run_id", ""))
    task_id = str(preview.get("task_id", ""))
    adapter_id = str(preview.get("adapter_id", ""))
    command = str(preview.get("command", ""))
    cwd = str(preview.get("working_directory", ""))
    scope_paths = tuple(str(p) for p in (preview.get("scope_paths") or []))
    preview_hash = compute_preview_hash(preview, adapter=adapter)

    approved_at_dt = datetime.now(timezone.utc)
    approved_at = approved_at_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    if ttl_minutes is not None:
        from datetime import timedelta

        expires = approved_at_dt + timedelta(minutes=ttl_minutes)
        expires_at = expires.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    else:
        expires_at = default_approval_expires_at(approval_level, approved_at=approved_at_dt)

    return ApprovalRecord(
        approval_id=new_approval_id(),
        task_id=task_id,
        run_id=run_id,
        preview_hash=preview_hash,
        adapter_id=adapter_id,
        approval_level=approval_level,
        approved_by=approved_by,
        approver_type=approver_type,
        approved_at=approved_at,
        expires_at=expires_at,
        scope="dispatch_execution",
        allowed_command_hash=command_hash(command),
        allowed_cwd=cwd,
        allowed_scope_paths=scope_paths,
        notes=notes,
        revoked=False,
    )


def save_approval_record(repo_root: Path, record: ApprovalRecord) -> Path:
    """Write approval record to runtime/dispatch/approvals/<approval_id>.json."""
    shape = validate_approval_record_shape(record)
    if not shape.well_formed:
        raise ValueError(f"approval record not well-formed: {shape.reasons}")

    approvals_dir = repo_root / "runtime" / "dispatch" / "approvals"
    approvals_dir.mkdir(parents=True, exist_ok=True)
    path = approvals_dir / f"{record.approval_id}.json"
    path.write_text(
        json.dumps(approval_record_to_dict(record), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def load_approval_record(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("approval record must be a JSON object")
    return data