"""Phase 3.2 controlled execution gate — preview-first, approval-gated, no subprocess."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dispatch.approval_contract import (
    ApprovalSatisfactionStatus,
    evaluate_approval_satisfaction,
)
from dispatch.executor_contract import (
    validate_cli_inventory_gate,
)
from dispatch.freshness import compute_preview_hash, is_preview_stale
from dispatch.preview import validate_command_allowlist
from dispatch.approval_replay import is_approval_consumed
from dispatch.approval_signing import SIGNING_VERSION, verify_signed_approval
from dispatch.execution_route_policy import (
    ROUTE_GENERIC_DISPATCH,
    evaluate_execution_route,
)
from dispatch.worktree_allocator import evaluate_allocation_for_execution
from dispatch.worktree_policy import evaluate_worktree_policy

MAX_TIMEOUT_SECONDS = 3600

# Phase 3.2: only adapters explicitly marked supports_execution may run subprocess.
EXECUTION_CAPABLE_FIELD = "supports_execution"


@dataclass
class ExecutionGateResult:
    execution_allowed: bool
    blocked_reasons: list[str] = field(default_factory=list)
    approval_status: ApprovalSatisfactionStatus = "none"
    approval_level: str = "none"
    preview_hash: str = ""
    warnings: list[str] = field(default_factory=list)
    execution_route_requested: str = ROUTE_GENERIC_DISPATCH
    execution_route_required: str | None = None
    execution_route_allowed: bool = True
    route_block_reasons: list[str] = field(default_factory=list)


def adapter_supports_execution(adapter: dict[str, Any] | None) -> bool:
    if not adapter:
        return False
    return bool(adapter.get(EXECUTION_CAPABLE_FIELD))


def evaluate_execution_gates(
    repo_root: Path,
    preview: dict[str, Any],
    *,
    adapter: dict[str, Any] | None,
    cli_inventory: dict[str, Any] | None,
    approval_record: dict[str, Any] | None = None,
    operator_execute: bool = False,
    dry_run: bool = False,
    worktree_root: str | None = None,
    allocation_record: dict[str, Any] | None = None,
    mcp_execution_allowed: bool = False,
    require_signed_approval: bool = True,
    check_replay: bool = False,
    now: datetime | None = None,
    execution_route: str = ROUTE_GENERIC_DISPATCH,
) -> ExecutionGateResult:
    """Evaluate all hard execution rules. Does not execute subprocess."""
    blocked: list[str] = []
    warnings: list[str] = []
    route_required: str | None = None
    route_allowed = True
    route_block_reasons: list[str] = []

    approval_gate = preview.get("approval_gate") or {}
    required_level = str(approval_gate.get("approval_level", "blocked"))
    preview_hash = compute_preview_hash(preview, adapter=adapter)

    if not operator_execute and not dry_run:
        blocked.append("explicit --execute or --dry-run operator flag required")

    if dry_run and operator_execute:
        blocked.append("cannot combine --dry-run and --execute")

    if not dry_run and not operator_execute:
        blocked.append("execution requires explicit --execute flag")

    if adapter is None:
        blocked.append(f"adapter {preview.get('adapter_id')!r} not found in registry")
    else:
        route_decision = evaluate_execution_route(adapter, execution_route)
        route_required = route_decision.required_route
        route_allowed = route_decision.allowed
        route_block_reasons = list(route_decision.reasons)
        if not route_decision.allowed:
            blocked.extend(route_decision.reasons)

        adapter_id = str(adapter.get("id", ""))
        if adapter.get("status") != "active":
            blocked.append(f"adapter {adapter_id!r} is not active")
        if not adapter.get("supports_dry_run"):
            blocked.append(f"adapter {adapter_id!r} does not support dry-run")
        if operator_execute and not dry_run:
            if not adapter_supports_execution(adapter):
                blocked.append(
                    f"adapter {adapter_id!r} does not support execution "
                    f"({EXECUTION_CAPABLE_FIELD}=false); preview-only"
                )

        command = str(preview.get("command", ""))
        blocked.extend(validate_command_allowlist(adapter, command))
        blocked.extend(validate_cli_inventory_gate(adapter, cli_inventory))

    timeout = preview.get("timeout_seconds")
    if timeout is None or int(timeout or 0) <= 0:
        blocked.append("missing or invalid: timeout_seconds")
    elif int(timeout) > MAX_TIMEOUT_SECONDS:
        blocked.append(f"timeout_seconds {timeout} exceeds max {MAX_TIMEOUT_SECONDS}")

    try:
        from dispatch.preview import load_plan, load_task_for_plan

        plan = load_plan(repo_root, preview.get("plan_path"))
        task = load_task_for_plan(repo_root, plan)
        stored_hash = str(preview.get("preview_hash") or "").strip()
        baseline_hash = stored_hash or compute_preview_hash(
            preview, adapter=adapter, task=task, plan=plan
        )
        if is_preview_stale(
            preview,
            current_adapter=adapter,
            current_task=task,
            current_plan=plan,
            baseline_hash=baseline_hash,
        ):
            blocked.append("preview is stale relative to current task/plan context")
    except Exception as exc:
        msg = f"preview freshness cannot be verified: {exc}"
        if operator_execute and not dry_run:
            blocked.append(msg)
        else:
            warnings.append(msg)

    if preview.get("secrets_required") and required_level != "human":
        blocked.append("secrets_required blocks execution without human approval level")

    mcp_required = str((adapter or {}).get("adapter_type", "")).lower() == "mcp"
    if mcp_required and not mcp_execution_allowed:
        blocked.append("mcp_required=true; MCP execution not allowed by policy")

    if required_level == "blocked":
        blocked.append("approval_gate level is blocked")

    risk_level = str((preview.get("risk_gate") or {}).get("approval_level", ""))
    if risk_level == "human" and required_level != "human":
        blocked.append("high-risk task requires human approval")

    satisfaction = evaluate_approval_satisfaction(
        approval_record,
        preview_hash,
        required_level,
        now=now,
    )
    approval_status = satisfaction.status

    if required_level in {"human", "reviewer"}:
        if not satisfaction.satisfied:
            blocked.extend(satisfaction.reasons)
            if satisfaction.status == "pending":
                blocked.append("approval record missing or insufficient")
        if approval_record is None:
            blocked.append("approval record required but not provided")
        elif require_signed_approval:
            version = int(approval_record.get("version", 1))
            if version >= SIGNING_VERSION:
                sig_result = verify_signed_approval(approval_record, preview=preview, now=now)
                if sig_result.status != "valid":
                    blocked.append(f"signed approval verification failed: {sig_result.status}")
                    for err in sig_result.errors:
                        blocked.append(err)
                if check_replay and is_approval_consumed(
                    repo_root, str(approval_record.get("approval_id", ""))
                ):
                    blocked.append("approval already consumed (replay blocked)")

    if preview.get("secrets_required"):
        if approval_record is None or str(approval_record.get("approver_type", "")) != "human":
            blocked.append("secrets_required requires human approval record")

    adapter_writes = bool((adapter or {}).get("writes_files"))
    worktree_required = bool(preview.get("worktree_required")) or adapter_writes
    effective_worktree_root = worktree_root
    if allocation_record is not None:
        effective_worktree_root = str(allocation_record.get("worktree_path", worktree_root or ""))

    if adapter_writes and worktree_required:
        base_sha = str(preview.get("base_sha") or preview.get("plan_base_sha") or "")
        if not base_sha:
            blocked.append("missing base_sha for worktree-bound file-writing execution")
        blocked.extend(
            evaluate_allocation_for_execution(
                allocation_record,
                task_id=str(preview.get("task_id", "")),
                run_id=str(preview.get("run_id", "")),
                base_sha=base_sha,
                cwd=str(preview.get("working_directory", "")),
                scope_paths=preview.get("scope_paths") or [],
            )
        )
        if allocation_record is None:
            blocked.append(
                "file-writing execution requires explicit worktree allocation record; "
                "automatic allocation is not enabled"
            )

    wd_result = evaluate_worktree_policy(
        repo_root,
        cwd=str(preview.get("working_directory", "")),
        scope_paths=preview.get("scope_paths") or [],
        writes_files=adapter_writes,
        worktree_required=worktree_required,
        worktree_root=effective_worktree_root,
    )
    blocked.extend(wd_result.blocked_reasons)

    if preview.get("errors"):
        for err in preview["errors"]:
            blocked.append(f"preview error: {err}")

    if not preview.get("dispatch_allowed"):
        warnings.append("preview dispatch_allowed=false — gate may still block execution")

    if not preview.get("handoff_path"):
        blocked.append("missing: handoff_path in preview")

    execution_allowed = len(blocked) == 0 and (
        dry_run or (operator_execute and not dry_run)
    )

    return ExecutionGateResult(
        execution_allowed=execution_allowed,
        blocked_reasons=blocked,
        approval_status=approval_status,
        approval_level=required_level,
        preview_hash=preview_hash,
        warnings=warnings,
        execution_route_requested=execution_route,
        execution_route_required=route_required,
        execution_route_allowed=route_allowed,
        route_block_reasons=route_block_reasons,
    )