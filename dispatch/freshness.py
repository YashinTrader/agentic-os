"""Phase 3.1 preview freshness and approval hash helpers — no execution."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from dispatch.approval_contract import ApprovalRecord, _parse_iso8601


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def preview_hash_payload(
    preview: dict[str, Any],
    *,
    adapter: dict[str, Any] | None = None,
    task: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic hash input from preview and optional live context."""
    approval_gate = preview.get("approval_gate") or {}
    risk_gate = preview.get("risk_gate") or {}
    adapter_id = (adapter or {}).get("id") or preview.get("adapter_id", "")
    task_id = (task or {}).get("id") or preview.get("task_id", "")
    approval_level = approval_gate.get("approval_level") or preview.get("approval_level", "")
    risk_level = (
        (task or {}).get("risk_level")
        or (adapter or {}).get("risk_level")
        or risk_gate.get("risk_level")
        or ""
    )

    return {
        "command": preview.get("command", ""),
        "cwd": preview.get("working_directory", ""),
        "scope_paths": sorted(preview.get("scope_paths") or []),
        "adapter_id": adapter_id,
        "task_id": task_id,
        "approval_level": approval_level,
        "risk_level": risk_level,
    }


def compute_preview_hash(
    preview: dict[str, Any],
    *,
    adapter: dict[str, Any] | None = None,
    task: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
) -> str:
    """MVP deterministic SHA-256 over canonical JSON of hash-relevant preview fields."""
    payload = preview_hash_payload(preview, adapter=adapter, task=task, plan=plan)
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return digest


def is_approval_fresh(preview_hash: str, approval_record: ApprovalRecord | dict[str, Any]) -> bool:
    """True when approval matches preview hash, is not revoked, and not expired."""
    if isinstance(approval_record, ApprovalRecord):
        record = approval_record
    else:
        record = ApprovalRecord(
            approval_id=str(approval_record.get("approval_id", "")),
            task_id=str(approval_record.get("task_id", "")),
            run_id=str(approval_record.get("run_id", "")),
            preview_hash=str(approval_record.get("preview_hash", "")),
            adapter_id=str(approval_record.get("adapter_id", "")),
            approval_level=str(approval_record.get("approval_level", "")),
            approved_by=str(approval_record.get("approved_by", "")),
            approver_type=str(approval_record.get("approver_type", "")),
            approved_at=str(approval_record.get("approved_at", "")),
            expires_at=str(approval_record.get("expires_at", "")),
            scope=str(approval_record.get("scope", "")),
            allowed_command_hash=str(approval_record.get("allowed_command_hash", "")),
            allowed_cwd=str(approval_record.get("allowed_cwd", "")),
            allowed_scope_paths=tuple(approval_record.get("allowed_scope_paths") or []),
            notes=str(approval_record.get("notes", "")),
            revoked=bool(approval_record.get("revoked")),
        )

    if record.revoked:
        return False
    if record.preview_hash != preview_hash:
        return False
    expires = _parse_iso8601(record.expires_at)
    if expires is None:
        return False
    return expires > datetime.now(timezone.utc)


def is_preview_stale(
    preview: dict[str, Any],
    *,
    current_adapter: dict[str, Any] | None = None,
    current_task: dict[str, Any] | None = None,
    current_plan: dict[str, Any] | None = None,
    baseline_hash: str | None = None,
) -> bool:
    """True when live context would change the preview hash vs baseline."""
    current = compute_preview_hash(
        preview,
        adapter=current_adapter,
        task=current_task,
        plan=current_plan,
    )
    if baseline_hash is None:
        baseline_hash = compute_preview_hash(preview)
    return current != baseline_hash