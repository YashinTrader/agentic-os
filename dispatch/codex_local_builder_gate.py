"""Local-builder gates — standing policy, no per-run approval."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dispatch.execution_policy import (
    MODE_AUTO_LOCAL_WORKTREE,
    load_execution_policy,
    policy_enabled_for_adapter,
    validate_execution_policy,
)
from dispatch.execution_route_policy import ROUTE_CODEX_LOCAL_BUILDER, evaluate_execution_route
from dispatch.path_containment import path_is_inside

FORBIDDEN_LOCAL_OPERATIONS = frozenset(
    {
        "git_push",
        "git_merge",
        "deploy",
        "production_access",
        "mcp_execution",
        "mcp_invoke",
        "browser_automation",
        "email_side_effects",
    }
)


@dataclass
class LocalBuilderGateResult:
    allowed: bool
    blocked_reasons: list[str] = field(default_factory=list)
    gate_results: dict[str, bool] = field(default_factory=dict)


def task_execution_mode(task: dict[str, Any]) -> str:
    execution = task.get("execution") or {}
    if not isinstance(execution, dict):
        return ""
    return str(execution.get("mode", "")).strip()


def task_adapter_id(task: dict[str, Any]) -> str:
    execution = task.get("execution") or {}
    if isinstance(execution, dict) and execution.get("adapter"):
        return str(execution["adapter"])
    return "codex-restricted"


def path_matches_allowed(relative_path: str, allowed_patterns: list[str]) -> bool:
    normalized = relative_path.replace("\\", "/").lstrip("./")
    for pattern in allowed_patterns:
        pat = pattern.replace("\\", "/")
        if fnmatch.fnmatch(normalized, pat) or fnmatch.fnmatch(normalized, pat.rstrip("/") + "/**"):
            return True
        if normalized.startswith(pat.rstrip("/") + "/"):
            return True
    return False


def evaluate_changed_paths_scope(
    worktree_root: Path,
    changed_paths: list[str],
    allowed_patterns: list[str],
) -> tuple[bool, list[str]]:
    violations: list[str] = []
    for rel in changed_paths:
        rel_norm = rel.replace("\\", "/").strip()
        if not rel_norm:
            continue
        if not path_matches_allowed(rel_norm, allowed_patterns):
            violations.append(f"path outside allowed scope: {rel_norm}")
        abs_path = (worktree_root / rel_norm).resolve()
        if not path_is_inside(abs_path, worktree_root.resolve(), allow_equal=True):
            violations.append(f"path escapes worktree: {rel_norm}")
    return (len(violations) == 0, violations)


def evaluate_local_builder_gates(
    repo_root: Path,
    *,
    task: dict[str, Any],
    adapter: dict[str, Any],
    allocation_record: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> LocalBuilderGateResult:
    blocked: list[str] = []
    gates: dict[str, bool] = {}

    repo_root = repo_root.resolve()
    adapter_id = str(adapter.get("id", ""))

    try:
        loaded_policy = policy if policy is not None else load_execution_policy(repo_root)
    except (OSError, ValueError) as exc:
        gates["policy_present"] = False
        blocked.append(f"execution policy unavailable: {exc}")
        return LocalBuilderGateResult(allowed=False, blocked_reasons=blocked, gate_results=gates)

    gates["policy_present"] = True
    policy_errors = validate_execution_policy(loaded_policy)
    gates["policy_valid"] = not policy_errors
    if policy_errors:
        blocked.extend(policy_errors)

    gates["policy_mode"] = str(loaded_policy.get("mode", "")) == MODE_AUTO_LOCAL_WORKTREE
    if not gates["policy_mode"]:
        blocked.append("execution policy mode must be auto_local_worktree")

    gates["policy_adapter_enabled"] = policy_enabled_for_adapter(loaded_policy, adapter_id)
    if not gates["policy_adapter_enabled"]:
        blocked.append(f"adapter {adapter_id!r} not enabled in standing policy")

    route = evaluate_execution_route(adapter, ROUTE_CODEX_LOCAL_BUILDER)
    gates["execution_route"] = route.allowed
    if not route.allowed:
        blocked.extend(route.reasons)

    gates["adapter_id"] = adapter_id == "codex-restricted"
    if not gates["adapter_id"]:
        blocked.append("local builder requires codex-restricted adapter")

    mode = task_execution_mode(task)
    gates["task_execution_mode"] = mode == MODE_AUTO_LOCAL_WORKTREE
    if not gates["task_execution_mode"]:
        blocked.append("task execution.mode must be auto_local_worktree")

    task_adapter = task_adapter_id(task)
    gates["task_adapter_match"] = task_adapter == adapter_id
    if not gates["task_adapter_match"]:
        blocked.append(f"task execution.adapter must be {adapter_id!r}")

    execution = task.get("execution") or {}
    forbidden = set(execution.get("forbidden_operations") or [])
    missing_forbidden = sorted(FORBIDDEN_LOCAL_OPERATIONS - forbidden)
    gates["forbidden_operations"] = not missing_forbidden
    if missing_forbidden:
        blocked.append(f"task must declare forbidden operations: {missing_forbidden}")

    gates["worktree_allocated"] = bool(
        allocation_record
        and allocation_record.get("worktree_path")
        and allocation_record.get("allocation_id")
    )
    if not gates["worktree_allocated"]:
        blocked.append("worktree allocation required")

    if allocation_record:
        wt_path = Path(str(allocation_record.get("worktree_path", ""))).resolve()
        gates["worktree_not_canonical"] = wt_path != repo_root.resolve()
        if not gates["worktree_not_canonical"]:
            blocked.append("worktree must not be the canonical checkout")
        gates["cwd_inside_worktree"] = path_is_inside(wt_path, wt_path, allow_equal=True)
        if allocation_record.get("task_id") and str(allocation_record["task_id"]) != str(task.get("id", "")):
            blocked.append("allocation task_id mismatch")

    gates["no_approval_required"] = True
    if adapter.get("phase3_7b_authorization_required"):
        blocked.append("phase3_7b_authorization_required must be false for auto_local_worktree")
        gates["no_approval_required"] = False

    return LocalBuilderGateResult(
        allowed=len(blocked) == 0,
        blocked_reasons=blocked,
        gate_results=gates,
    )