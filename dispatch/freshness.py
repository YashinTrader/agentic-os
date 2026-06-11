"""Phase 3.1 preview freshness and approval hash helpers — no execution."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from dispatch.approval_contract import (
    ApprovalRecord,
    evaluate_approval_satisfaction,
)


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


def is_approval_fresh(
    preview_hash: str,
    approval_record: ApprovalRecord | dict[str, Any],
    *,
    required_approval_level: str = "reviewer",
    now: datetime | None = None,
) -> bool:
    """True when approval satisfies required level for the given preview hash."""
    result = evaluate_approval_satisfaction(
        approval_record,
        preview_hash,
        required_approval_level,
        now=now,
    )
    return result.satisfied


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