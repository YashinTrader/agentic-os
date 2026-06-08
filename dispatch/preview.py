"""Dry-run dispatch command preview — no subprocess execution."""

from __future__ import annotations

import json
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from orchestrator.loaders import load_task_yaml, resolve_task_path
from orchestrator.risk import evaluate_risk

APPROVAL_PRECEDENCE = {"none": 0, "reviewer": 1, "human": 2, "blocked": 3}

ADAPTER_REQUIRED_FIELDS = {
    "id",
    "display_name",
    "agent_id",
    "adapter_type",
    "status",
    "command_template",
    "allowed_commands",
    "forbidden_args",
    "required_clis",
    "env_vars_required",
    "secrets_required",
    "timeout_seconds",
    "working_directory_policy",
    "supports_dry_run",
    "supports_streaming",
    "writes_files",
    "approval_level",
    "risk_level",
    "notes",
}

ALLOWED_ADAPTER_TYPES = {"cli", "mcp", "http"}
ALLOWED_WD_POLICIES = {"repo_root", "worktree", "task_subdir"}
ALLOWED_ADAPTER_STATUSES = {"active", "disabled", "planned"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_dispatch_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"dispatch-{stamp}-{uuid4().hex[:8]}"


def load_adapter_registry(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "agents" / "adapter_registry.yaml"
    if not path.exists():
        raise FileNotFoundError(f"adapter registry not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("adapter_registry.yaml root must be a mapping")
    adapters = data.get("adapters")
    if not isinstance(adapters, list):
        raise ValueError("adapter_registry.yaml adapters must be a list")
    return data


def get_adapter_by_id(registry: dict[str, Any], adapter_id: str) -> dict[str, Any] | None:
    for adapter in registry.get("adapters", []):
        if isinstance(adapter, dict) and str(adapter.get("id")) == adapter_id:
            return adapter
    return None


def get_adapter_for_agent(registry: dict[str, Any], agent_id: str) -> dict[str, Any] | None:
    agent_lower = agent_id.lower()
    for adapter in registry.get("adapters", []):
        if not isinstance(adapter, dict):
            continue
        if str(adapter.get("agent_id", "")).lower() == agent_lower and adapter.get("status") == "active":
            return adapter
    return None


def load_plan(repo_root: Path, plan_path: str | None = None) -> dict[str, Any]:
    if plan_path:
        path = Path(plan_path)
        if not path.is_absolute():
            path = (repo_root / path).resolve()
    else:
        path = (repo_root / "runtime" / "orchestrator" / "latest_plan.json").resolve()
    if not path.exists():
        raise FileNotFoundError(f"orchestration plan not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("plan must be a JSON object")
    return data


def load_orchestrator_state(repo_root: Path) -> dict[str, Any] | None:
    path = repo_root / "runtime" / "orchestrator" / "latest_state.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def load_task_for_plan(repo_root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    task_id = str(plan.get("task_id", ""))
    if not task_id:
        raise ValueError("plan missing task_id")
    for folder in ("active", "blocked", "done"):
        candidate = repo_root / "tasks" / folder / f"{task_id}.yaml"
        if candidate.exists():
            return load_task_yaml(candidate)
    raise FileNotFoundError(f"task YAML not found for {task_id}")


def expand_command_template(template: str, context: dict[str, str]) -> str:
    result = template
    for key, value in context.items():
        result = result.replace("{" + key + "}", value)
    return result


def _command_root(command: str) -> str:
    try:
        parts = shlex.split(command, posix=False)
    except ValueError:
        parts = command.split()
    if not parts:
        return ""
    root = Path(parts[0]).name.lower()
    if root.endswith(".exe"):
        root = root[:-4]
    return root


def validate_command_allowlist(adapter: dict[str, Any], command: str) -> list[str]:
    errors: list[str] = []
    if not adapter.get("supports_dry_run"):
        errors.append(f"adapter {adapter.get('id')} does not support dry-run preview")
    if adapter.get("status") != "active":
        errors.append(f"adapter {adapter.get('id')} status is {adapter.get('status')!r}")

    allowed = {str(c).lower() for c in adapter.get("allowed_commands", [])}
    root = _command_root(command)
    if allowed and root not in allowed:
        errors.append(f"command root {root!r} not in allowed_commands {sorted(allowed)}")

    cmd_lower = command.lower()
    for forbidden in adapter.get("forbidden_args", []):
        if str(forbidden).lower() in cmd_lower:
            errors.append(f"forbidden argument present: {forbidden!r}")

    return errors


def resolve_working_directory(repo_root: Path, policy: str) -> str:
    if policy not in ALLOWED_WD_POLICIES:
        raise ValueError(f"unknown working_directory_policy: {policy}")
    if policy == "repo_root":
        return str(repo_root.resolve())
    if policy == "task_subdir":
        return str((repo_root / "tasks").resolve())
    return str(repo_root.resolve())


def stricter_approval_level(a: str, b: str) -> str:
    a_norm = a if a in APPROVAL_PRECEDENCE else "none"
    b_norm = b if b in APPROVAL_PRECEDENCE else "none"
    return a_norm if APPROVAL_PRECEDENCE[a_norm] >= APPROVAL_PRECEDENCE[b_norm] else b_norm


def merge_approval_gate(risk_result: dict[str, Any], adapter: dict[str, Any]) -> dict[str, Any]:
    adapter_level = str(adapter.get("approval_level", "reviewer"))
    risk_level = str(risk_result.get("approval_level", "none"))
    merged = stricter_approval_level(risk_level, adapter_level)
    required = merged in {"human", "reviewer", "blocked"} or bool(risk_result.get("approval_required"))
    reasons = []
    if risk_result.get("approval_reason"):
        reasons.append(str(risk_result["approval_reason"]))
    if adapter_level != "none" and adapter_level != risk_level:
        reasons.append(f"Adapter default approval_level: {adapter_level}")
    status = "pending"
    if merged == "blocked":
        status = "blocked"
    elif merged == "none":
        status = "none"
    elif merged == "human":
        status = "pending_human"
    else:
        status = "pending_reviewer"
    return {
        "approval_level": merged,
        "approval_required": required,
        "approval_status": status,
        "approval_reason": " | ".join(reasons) if reasons else "Routine preview.",
    }


def _scope_paths(repo_root: Path, plan: dict[str, Any], task: dict[str, Any]) -> list[str]:
    paths: set[str] = {"tasks/", "handoffs/", "logs/", "runtime/orchestrator/"}
    for item in plan.get("files_to_inspect", []):
        if isinstance(item, str):
            paths.add(item)
    for field in ("inputs", "outputs"):
        for item in task.get(field, []):
            if isinstance(item, str) and ("/" in item or "\\" in item):
                paths.add(item)
    return sorted(paths)


def _rollback_strategy(adapter: dict[str, Any]) -> str:
    if adapter.get("writes_files"):
        return (
            "Phase 3.2+: snapshot or git worktree before execution; "
            "document rollback steps in handoff."
        )
    return "Read-only preview — no file rollback required."


def build_dispatch_preview(
    repo_root: Path,
    *,
    adapter_id: str | None = None,
    plan_path: str | None = None,
    task_path: str | None = None,
) -> dict[str, Any]:
    """Build a dry-run dispatch preview. Never executes subprocesses."""
    repo_root = repo_root.resolve()
    run_id = new_dispatch_run_id()
    errors: list[str] = []
    warnings: list[str] = []

    registry = load_adapter_registry(repo_root)
    plan = load_plan(repo_root, plan_path)

    try:
        if task_path:
            resolved = resolve_task_path(repo_root, task_path, must_exist=True)
            task = load_task_yaml(resolved)
        else:
            task = load_task_for_plan(repo_root, plan)
    except Exception as exc:
        errors.append(f"task load failed: {exc}")
        task = {}

    state = load_orchestrator_state(repo_root) or {}
    risk_result = evaluate_risk(task, {**state, **plan}) if task else {
        "approval_required": True,
        "approval_level": "blocked",
        "approval_reason": "Task unavailable for risk evaluation.",
    }

    agent_id = str(plan.get("recommended_primary_agent", task.get("owner", "composer")))
    adapter = None
    if adapter_id:
        adapter = get_adapter_by_id(registry, adapter_id)
        if not adapter:
            errors.append(f"unknown adapter id: {adapter_id}")
    else:
        adapter = get_adapter_for_agent(registry, agent_id)
        if not adapter:
            errors.append(f"no active adapter for agent {agent_id!r}")

    task_id = str(plan.get("task_id") or task.get("id", ""))
    orch_state = state
    plan_path_val = str(orch_state.get("plan_path") or plan_path or "runtime/orchestrator/latest_plan.json")
    ctx_path_val = str(orch_state.get("context_pack_path") or "")

    command = ""
    allowlist_errors: list[str] = []
    if adapter:
        context = {
            "task_id": task_id,
            "plan_path": plan_path_val,
            "context_pack_path": ctx_path_val,
            "run_id": str(plan.get("run_id") or state.get("run_id", "")),
            "agent_id": agent_id,
            "mcp_id": "",
            "tool_name": "",
        }
        command = expand_command_template(str(adapter.get("command_template", "")), context)
        allowlist_errors = validate_command_allowlist(adapter, command)
        errors.extend(allowlist_errors)

    approval = (
        merge_approval_gate(risk_result, adapter)
        if adapter
        else {
            "approval_level": risk_result.get("approval_level", "blocked"),
            "approval_required": True,
            "approval_status": "blocked",
            "approval_reason": risk_result.get("approval_reason", "No adapter selected."),
        }
    )

    dispatch_allowed = (
        not errors
        and approval.get("approval_level") != "blocked"
        and adapter is not None
        and adapter.get("supports_dry_run") is True
        and adapter.get("status") == "active"
    )

    wd_policy = str(adapter.get("working_directory_policy", "repo_root")) if adapter else "repo_root"
    working_directory = resolve_working_directory(repo_root, wd_policy)

    handoff_path = f"handoffs/{task_id}__{agent_id}__to__{plan.get('recommended_reviewer', 'claude')}.md"
    log_path = f"logs/dispatch-{run_id}.jsonl"

    preview: dict[str, Any] = {
        "schema_version": "1.0",
        "run_id": run_id,
        "created_at": utc_now(),
        "phase": "3.0",
        "mode": "dry_run_preview",
        "executed": False,
        "dispatch_allowed": dispatch_allowed,
        "task_id": task_id,
        "adapter_id": adapter.get("id") if adapter else None,
        "adapter_display_name": adapter.get("display_name") if adapter else None,
        "agent_id": agent_id,
        "command": command,
        "working_directory": working_directory,
        "scope_paths": _scope_paths(repo_root, plan, task) if task else [],
        "timeout_seconds": adapter.get("timeout_seconds") if adapter else None,
        "env_vars_required": list(adapter.get("env_vars_required", [])) if adapter else [],
        "secrets_required": bool(adapter.get("secrets_required")) if adapter else False,
        "expected_outputs": [
            f"Preview artifact: runtime/dispatch/previews/{run_id}/preview.json",
            f"Dispatch log: {log_path}",
            f"Proposed handoff: {handoff_path}",
        ],
        "logs_path": log_path,
        "handoff_path": handoff_path,
        "rollback_strategy": _rollback_strategy(adapter) if adapter else "N/A",
        "risk_gate": {
            "approval_level": risk_result.get("approval_level"),
            "approval_required": risk_result.get("approval_required"),
            "approval_reason": risk_result.get("approval_reason"),
        },
        "approval_gate": approval,
        "plan_path": plan_path_val,
        "context_pack_path": ctx_path_val or None,
        "errors": errors,
        "warnings": warnings,
        "statement": "Dry-run preview only. No agents were launched. No subprocess executed.",
    }
    return preview


def persist_preview(repo_root: Path, preview: dict[str, Any], *, write_artifacts: bool = True) -> dict[str, str]:
    """Write preview JSON and dispatch log line. Does not execute commands."""
    paths: dict[str, str] = {}
    if not write_artifacts:
        return paths

    run_id = str(preview["run_id"])
    preview_dir = repo_root / "runtime" / "dispatch" / "previews" / run_id
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_path = preview_dir / "preview.json"
    preview_path.write_text(json.dumps(preview, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["preview_path"] = str(preview_path.relative_to(repo_root))

    latest_dir = repo_root / "runtime" / "dispatch"
    latest_dir.mkdir(parents=True, exist_ok=True)
    latest_path = latest_dir / "latest_preview.json"
    latest_path.write_text(json.dumps(preview, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["latest_preview_path"] = str(latest_path.relative_to(repo_root))

    log_path = repo_root / preview["logs_path"]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_line = {
        "ts": preview["created_at"],
        "run_id": run_id,
        "mode": preview["mode"],
        "dispatch_allowed": preview["dispatch_allowed"],
        "task_id": preview.get("task_id"),
        "adapter_id": preview.get("adapter_id"),
        "approval_level": preview.get("approval_gate", {}).get("approval_level"),
    }
    with log_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(log_line, separators=(",", ":"), ensure_ascii=False) + "\n")
    paths["logs_path"] = str(log_path.relative_to(repo_root))

    return paths


def append_preview_event(repo_root: Path, preview: dict[str, Any]) -> None:
    from protocol.emit_event import append_event

    event_type = "dispatch_preview_created" if preview.get("dispatch_allowed") else "dispatch_blocked"
    append_event(
        repo_root,
        agent="dispatch-preview",
        event_type=event_type,
        task_id=str(preview.get("task_id", "")),
        detail=(
            f"dispatch preview run_id={preview.get('run_id')} "
            f"adapter={preview.get('adapter_id')} allowed={preview.get('dispatch_allowed')}"
        ),
        ref=preview.get("logs_path", ""),
    )