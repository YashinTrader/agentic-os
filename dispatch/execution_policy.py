"""Standing execution policy for autonomous local worktree development."""

from __future__ import annotations

from pathlib import Path
from typing import Any

POLICY_REL_PATH = "config/execution-policy.yaml"
MODE_AUTO_LOCAL_WORKTREE = "auto_local_worktree"


def policy_path(repo_root: Path) -> Path:
    return repo_root / POLICY_REL_PATH


def load_execution_policy(repo_root: Path) -> dict[str, Any]:
    path = policy_path(repo_root)
    if not path.is_file():
        raise FileNotFoundError(f"execution policy missing: {path}")
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("execution policy root must be a mapping")
    return data


def policy_enabled_for_adapter(policy: dict[str, Any], adapter_id: str) -> bool:
    if not policy.get("enabled"):
        return False
    if str(policy.get("mode", "")) != MODE_AUTO_LOCAL_WORKTREE:
        return False
    enabled = policy.get("enabled_adapters") or []
    return adapter_id in enabled


def validate_execution_policy(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if int(policy.get("version", 0)) != 1:
        errors.append("execution policy version must be 1")
    if str(policy.get("mode", "")) != MODE_AUTO_LOCAL_WORKTREE:
        errors.append(f"unsupported execution policy mode: {policy.get('mode')!r}")
    if not policy.get("enabled"):
        errors.append("execution policy must be enabled")
    if not policy.get("enabled_adapters"):
        errors.append("enabled_adapters must be non-empty")
    if policy.get("allow_merge") or policy.get("allow_push") or policy.get("allow_deploy"):
        errors.append("merge/push/deploy must be disabled in auto_local_worktree policy")
    if policy.get("allow_mcp_execution"):
        errors.append("MCP execution must be disabled")
    if policy.get("allow_production_access"):
        errors.append("production access must be disabled")
    if int(policy.get("automatic_retry_count", 0) or 0) != 0:
        errors.append("automatic_retry_count must be 0")
    if int(policy.get("maximum_concurrent_runs", 0) or 0) < 1:
        errors.append("maximum_concurrent_runs must be >= 1")
    return errors