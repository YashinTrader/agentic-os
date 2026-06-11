"""Phase 3.1 controlled executor contract — types and validation only. No execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from dispatch.preview import get_adapter_by_id, load_adapter_registry

APPROVAL_LEVELS = frozenset({"none", "reviewer", "human", "blocked"})
APPROVAL_STATUSES = frozenset(
    {"none", "pending_reviewer", "pending_human", "approved", "blocked", "expired", "revoked"}
)

EXECUTOR_LIFECYCLE_STEPS = (
    "load_orchestration_plan",
    "load_adapter_config",
    "verify_adapter_active_and_allowlisted",
    "verify_cli_inventory",
    "verify_command_preview_exists",
    "verify_preview_freshness",
    "verify_approval_requirement",
    "verify_approval_record_if_required",
    "verify_worktree_sandbox_policy",
    "create_execution_run_id",
    "capture_stdout_stderr_logs_runtime_only",
    "write_dispatch_event_logs",
    "require_handoff",
    "never_auto_merge",
    "never_mutate_main_branch",
)


@dataclass(frozen=True)
class ExecutionPlanReference:
    task_id: str
    plan_path: str
    preview_path: str


@dataclass(frozen=True)
class ExecutionSafetyEnvelope:
    writes_files: bool
    secrets_required: bool
    network_required: bool
    mcp_required: bool
    worktree_required: bool
    scope_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionRequest:
    run_id: str
    task_id: str
    plan_path: str
    preview_path: str
    adapter_id: str
    selected_agent: str
    command_preview: str
    cwd: str
    scope_paths: tuple[str, ...]
    timeout_seconds: int
    approval_level: str
    approval_status: str
    approval_record_path: str | None
    worktree_required: bool
    writes_files: bool
    secrets_required: bool
    network_required: bool
    mcp_required: bool
    executed: bool = False
    execution_allowed: bool = False
    blocked_reasons: tuple[str, ...] = ()
    logs_path: str = ""
    handoff_path: str = ""
    rollback_notes: str = ""


@dataclass(frozen=True)
class ExecutionResultContract:
    run_id: str
    executed: bool
    exit_code: int | None
    timed_out: bool
    started_at: str
    finished_at: str
    duration_ms: int
    stdout_path: str
    stderr_path: str
    files_changed: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    error: str | None
    handoff_path: str


@dataclass(frozen=True)
class ExecutorContract:
    schema_version: str = "1.0"
    phase: str = "3.1"
    mode: str = "design_contract"
    lifecycle_steps: tuple[str, ...] = EXECUTOR_LIFECYCLE_STEPS
    statement: str = (
        "Phase 3.1 design contract only. No subprocess, agent, MCP, or LLM execution."
    )


@dataclass
class ExecutionValidationResult:
    valid: bool
    execution_allowed: bool
    blocked_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def execution_request_to_dict(request: ExecutionRequest) -> dict[str, Any]:
    return asdict(request)


def load_cli_inventory(repo_root: Path) -> dict[str, Any] | None:
    path = repo_root / "runtime" / "registry" / "cli_inventory.yaml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def validate_cli_inventory_gate(
    adapter: dict[str, Any],
    cli_inventory: dict[str, Any] | None,
) -> list[str]:
    """Pure validation: required CLIs must exist and be available in inventory."""
    errors: list[str] = []
    required = adapter.get("required_clis") or []
    if not required:
        return errors
    if cli_inventory is None:
        errors.append(
            "CLI inventory missing at runtime/registry/cli_inventory.yaml; "
            f"required_clis={list(required)}"
        )
        return errors

    tools = cli_inventory.get("tools") or []
    if not isinstance(tools, list):
        errors.append("cli_inventory.tools must be a list")
        return errors

    by_name: dict[str, dict[str, Any]] = {}
    for tool in tools:
        if isinstance(tool, dict) and tool.get("name"):
            by_name[str(tool["name"]).lower()] = tool

    for cli_name in required:
        key = str(cli_name).lower()
        entry = by_name.get(key)
        if entry is None:
            errors.append(f"required CLI {cli_name!r} not found in cli_inventory.yaml")
            continue
        if not entry.get("available"):
            errors.append(f"required CLI {cli_name!r} is not available (available=false)")
            continue
        cli_path = entry.get("path")
        if not cli_path:
            errors.append(f"required CLI {cli_name!r} has no path in cli_inventory.yaml")

    return errors


def _classify_required_field_issues(request: ExecutionRequest) -> tuple[list[str], list[str]]:
    """Return (missing_fields, invalid_fields) with distinct semantics."""
    missing: list[str] = []
    invalid: list[str] = []

    if not request.run_id:
        missing.append("run_id")
    if not request.task_id:
        missing.append("task_id")
    if not request.plan_path:
        missing.append("plan_path")
    if not request.preview_path:
        missing.append("preview_path")
    if not request.adapter_id:
        missing.append("adapter_id")
    if not request.selected_agent:
        missing.append("selected_agent")
    if not request.command_preview:
        missing.append("command_preview")
    if not request.cwd:
        missing.append("cwd")

    if request.timeout_seconds <= 0:
        invalid.append("timeout_seconds")

    if request.approval_level not in APPROVAL_LEVELS:
        invalid.append("approval_level")
    if request.approval_status not in APPROVAL_STATUSES:
        invalid.append("approval_status")

    return missing, invalid


def _format_field_issues(missing: list[str], invalid: list[str]) -> list[str]:
    messages: list[str] = []
    if missing:
        messages.append(f"missing: {', '.join(missing)}")
    if invalid:
        messages.append(f"invalid: {', '.join(invalid)}")
    return messages


def resolve_mcp_required(adapter: dict[str, Any] | None) -> bool:
    """Derive mcp_required from adapter registry metadata, not adapter_id suffix."""
    if not adapter:
        return False
    adapter_type = str(adapter.get("adapter_type", "")).lower()
    if adapter_type == "mcp":
        return True
    return False


def validate_execution_request_contract(
    request: ExecutionRequest,
    *,
    adapter: dict[str, Any] | None = None,
    cli_inventory: dict[str, Any] | None = None,
) -> ExecutionValidationResult:
    """Validate execution request against Phase 3.1 safety contract. Does not execute."""
    blocked: list[str] = []
    warnings: list[str] = []

    missing, invalid = _classify_required_field_issues(request)
    blocked.extend(_format_field_issues(missing, invalid))

    if request.executed:
        blocked.append("executed must be false at request validation time (Phase 3.1 design)")

    if adapter is None:
        blocked.append(f"adapter {request.adapter_id!r} not found in registry")
    else:
        if adapter.get("status") != "active":
            blocked.append(
                f"adapter {adapter.get('id')!r} is not active (status={adapter.get('status')!r})"
            )
        if not adapter.get("supports_dry_run"):
            blocked.append(f"adapter {adapter.get('id')!r} does not support dry-run preview")

        if cli_inventory is not None or adapter.get("required_clis"):
            blocked.extend(validate_cli_inventory_gate(adapter, cli_inventory))

    if request.writes_files and not request.worktree_required:
        blocked.append(
            "writes_files=true requires worktree_required=true (ADR-0016 sandbox policy)"
        )

    if request.secrets_required and request.approval_level != "human":
        blocked.append("secrets_required implies approval_level must be human")

    if request.approval_level == "blocked":
        blocked.append("approval_level is blocked")

    if request.approval_level in {"human", "reviewer"}:
        if request.approval_status not in {"approved"}:
            blocked.append(
                f"approval_status {request.approval_status!r} insufficient for "
                f"approval_level {request.approval_level!r}"
            )
        if not request.approval_record_path:
            blocked.append("approval_record_path required when approval is required")

    if request.mcp_required:
        warnings.append("mcp_required=true — Phase 3.2 must enforce MCP sandbox separately")

    if request.network_required:
        warnings.append("network_required=true — Phase 3.2 must enforce network policy")

    blocked.extend(request.blocked_reasons)

    execution_allowed = len(blocked) == 0
    return ExecutionValidationResult(
        valid=len(missing) == 0 and len(invalid) == 0,
        execution_allowed=execution_allowed,
        blocked_reasons=blocked,
        warnings=warnings,
    )


def build_execution_request_from_preview(
    preview: dict[str, Any],
    *,
    approval_record_path: str | None = None,
    worktree_required: bool | None = None,
    adapter: dict[str, Any] | None = None,
) -> ExecutionRequest:
    """Map Phase 3.0 preview dict to Phase 3.1 execution request contract (no execution)."""
    approval_gate = preview.get("approval_gate") or {}
    adapter_writes = bool(adapter.get("writes_files")) if adapter else False
    wd_policy = str(adapter.get("working_directory_policy", "")) if adapter else ""
    inferred_worktree = wd_policy == "worktree" or adapter_writes
    if worktree_required is None and preview.get("worktree_required") is not None:
        resolved_worktree = bool(preview.get("worktree_required"))
    elif worktree_required is None:
        resolved_worktree = inferred_worktree
    else:
        resolved_worktree = worktree_required

    return ExecutionRequest(
        run_id=str(preview.get("run_id", "")),
        task_id=str(preview.get("task_id", "")),
        plan_path=str(preview.get("plan_path", "")),
        preview_path=str(preview.get("preview_path", "")),
        adapter_id=str(preview.get("adapter_id", "")),
        selected_agent=str(preview.get("agent_id", "")),
        command_preview=str(preview.get("command", "")),
        cwd=str(preview.get("working_directory", "")),
        scope_paths=tuple(preview.get("scope_paths") or []),
        timeout_seconds=int(preview.get("timeout_seconds") or 0),
        approval_level=str(approval_gate.get("approval_level", "blocked")),
        approval_status=str(approval_gate.get("approval_status", "blocked")),
        approval_record_path=approval_record_path,
        worktree_required=resolved_worktree,
        writes_files=adapter_writes,
        secrets_required=bool(preview.get("secrets_required")),
        network_required=False,
        mcp_required=resolve_mcp_required(adapter),
        executed=bool(preview.get("executed")),
        execution_allowed=bool(preview.get("dispatch_allowed")),
        blocked_reasons=tuple(preview.get("errors") or []),
        logs_path=str(preview.get("logs_path", "")),
        handoff_path=str(preview.get("handoff_path", "")),
        rollback_notes=str(preview.get("rollback_strategy", "")),
    )


def resolve_adapter_for_request(repo_root: Path, adapter_id: str) -> dict[str, Any] | None:
    registry = load_adapter_registry(repo_root)
    return get_adapter_by_id(registry, adapter_id)