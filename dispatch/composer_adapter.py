"""Composer restricted adapter — preview contract and loader (no subprocess)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_composer_restricted_adapter(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "agents" / "composer_restricted_adapter.yaml"
    if not path.exists():
        raise FileNotFoundError(f"composer restricted adapter config missing: {path}")
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("composer_restricted_adapter.yaml root must be a mapping")
    return data


def validate_composer_preview_contract(adapter: dict[str, Any]) -> list[str]:
    """Static preview contract checks for composer-restricted."""
    blocked: list[str] = []
    if adapter.get("id") != "composer-restricted":
        blocked.append("adapter id must be composer-restricted")
    if adapter.get("supports_execution"):
        blocked.append("composer-restricted must remain preview-only (supports_execution=false)")
    if str(adapter.get("status", "")) not in {"preview", "disabled"}:
        blocked.append("composer-restricted status must be preview until live activation")
    if str(adapter.get("required_execution_route", "")) != "composer_local_builder":
        blocked.append("required_execution_route must be composer_local_builder")
    if str(adapter.get("execution_scope", "")) != "local_worktree":
        blocked.append("execution_scope must be local_worktree")
    if adapter.get("secrets_required"):
        blocked.append("secrets_required must be false in preview scaffolding")
    denylist = frozenset(adapter.get("environment_denylist") or [])
    for required_deny in (
        "AGENTIC_OS_HUMAN_APPROVAL_KEY",
        "AGENTIC_OS_REVIEWER_APPROVAL_KEY",
        "GITHUB_TOKEN",
        "SUPABASE_KEY",
    ):
        if required_deny not in denylist:
            blocked.append(f"environment_denylist must include {required_deny}")
    return blocked