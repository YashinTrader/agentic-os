"""Codex activation manifest — pure validation, no activation side effects."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dispatch.codex_adapter import compute_command_contract_hash, load_codex_restricted_adapter
from dispatch.codex_canary_contract import compute_canary_contract_hash

ACTIVATION_MANIFEST_VERSION = "1.0"
ALLOWED_PRE_ACTIVE_STATUSES = frozenset(
    {"draft", "reviewer_approved", "awaiting_human_approval"}
)
FORBIDDEN_ACTIVE_STATUSES = frozenset(
    {"human_approved", "activation_ready", "active_canary_only", "active"}
)

REQUIRED_MANIFEST_FIELDS = (
    "activation_id",
    "version",
    "adapter_id",
    "adapter_config_hash",
    "cli_version",
    "cli_help_hash",
    "command_contract_hash",
    "canary_contract_hash",
    "worktree_policy_hash",
    "environment_policy_hash",
    "approval_policy_hash",
    "base_sha",
    "reviewed_commit_sha",
    "reviewer_approval_reference",
    "human_approval_required",
    "human_approval_reference",
    "activation_scope",
    "activation_expires_at",
    "maximum_runs",
    "canary_only",
    "created_at",
    "status",
)


@dataclass
class ActivationValidationResult:
    ready_for_review: bool
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_adapter_config_hash(adapter: dict[str, Any]) -> str:
    import yaml

    canonical = yaml.safe_dump(adapter, sort_keys=True)
    return _sha256_text(canonical)


def compute_policy_hashes(adapter: dict[str, Any]) -> dict[str, str]:
    worktree = {"worktree_required": True, "cwd_policy": "allocated_worktree_only"}
    environment = {
        "allowlist": sorted(adapter.get("environment_allowlist") or []),
        "denylist": sorted(adapter.get("environment_denylist") or []),
    }
    approval = {"approval_level": "human", "reviewer_insufficient": True}
    return {
        "worktree_policy_hash": _sha256_text(json.dumps(worktree, sort_keys=True)),
        "environment_policy_hash": _sha256_text(json.dumps(environment, sort_keys=True)),
        "approval_policy_hash": _sha256_text(json.dumps(approval, sort_keys=True)),
    }


def build_draft_activation_manifest(
    repo_root: Path,
    *,
    activation_id: str,
    reviewed_commit_sha: str,
    base_sha: str,
    cli_version: str,
    cli_help_hash: str,
    reviewer_approval_reference: str = "",
    status: str = "reviewer_approved",
) -> dict[str, Any]:
    adapter = load_codex_restricted_adapter(repo_root)
    policies = compute_policy_hashes(adapter)
    return {
        "activation_id": activation_id,
        "version": ACTIVATION_MANIFEST_VERSION,
        "adapter_id": "codex-restricted",
        "adapter_config_hash": compute_adapter_config_hash(adapter),
        "cli_version": cli_version,
        "cli_help_hash": cli_help_hash,
        "command_contract_hash": compute_command_contract_hash(),
        "canary_contract_hash": compute_canary_contract_hash(),
        "worktree_policy_hash": policies["worktree_policy_hash"],
        "environment_policy_hash": policies["environment_policy_hash"],
        "approval_policy_hash": policies["approval_policy_hash"],
        "base_sha": base_sha,
        "reviewed_commit_sha": reviewed_commit_sha,
        "reviewer_approval_reference": reviewer_approval_reference,
        "human_approval_required": True,
        "human_approval_reference": "",
        "activation_scope": "canary_only",
        "activation_expires_at": "2099-01-01T00:00:00Z",
        "maximum_runs": 1,
        "canary_only": True,
        "created_at": utc_now(),
        "status": status,
        "disabled_reason": "",
    }


def validate_activation_manifest(
    manifest: dict[str, Any],
    *,
    repo_root: Path,
    current_reviewed_sha: str | None = None,
    cli_help_hash: str | None = None,
    now: datetime | None = None,
) -> ActivationValidationResult:
    blockers: list[str] = []
    warnings: list[str] = []

    for field_name in REQUIRED_MANIFEST_FIELDS:
        if field_name not in manifest:
            blockers.append(f"manifest missing field: {field_name}")

    status = str(manifest.get("status", ""))
    if status in FORBIDDEN_ACTIVE_STATUSES:
        blockers.append(f"manifest status {status!r} not allowed in Phase 3.6")
    if status and status not in ALLOWED_PRE_ACTIVE_STATUSES and status not in FORBIDDEN_ACTIVE_STATUSES:
        blockers.append(f"unknown manifest status: {status!r}")

    if manifest.get("adapter_id") != "codex-restricted":
        blockers.append("adapter_id must be codex-restricted")
    if not manifest.get("canary_only"):
        blockers.append("canary_only must be true")
    if manifest.get("activation_scope") != "canary_only":
        blockers.append("activation_scope must be canary_only")
    if int(manifest.get("maximum_runs", 0) or 0) != 1:
        blockers.append("maximum_runs must equal 1")
    if not manifest.get("human_approval_required"):
        blockers.append("human_approval_required must be true")

    try:
        adapter = load_codex_restricted_adapter(repo_root)
    except (OSError, ValueError) as exc:
        blockers.append(f"adapter config unavailable: {exc}")
        adapter = {}

    if adapter:
        if adapter.get("supports_execution"):
            blockers.append("adapter supports_execution must remain false")
        expected_config_hash = compute_adapter_config_hash(adapter)
        if str(manifest.get("adapter_config_hash", "")) != expected_config_hash:
            blockers.append("adapter_config_hash does not match current candidate config")

    expected_cmd_hash = compute_command_contract_hash()
    if str(manifest.get("command_contract_hash", "")) != expected_cmd_hash:
        blockers.append("command_contract_hash does not match current command contract")

    expected_canary_hash = compute_canary_contract_hash()
    if str(manifest.get("canary_contract_hash", "")) != expected_canary_hash:
        blockers.append("canary_contract_hash does not match current canary contract")

    if current_reviewed_sha and str(manifest.get("reviewed_commit_sha", "")) != current_reviewed_sha:
        blockers.append("reviewed_commit_sha does not match current reviewed commit")

    if cli_help_hash and str(manifest.get("cli_help_hash", "")) != cli_help_hash:
        blockers.append("cli_help_hash does not match current CLI help")

    expires_raw = str(manifest.get("activation_expires_at", ""))
    if expires_raw:
        try:
            expires = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
            ref = now or datetime.now(timezone.utc)
            if ref > expires:
                blockers.append("activation manifest expired")
        except ValueError:
            blockers.append("activation_expires_at malformed")

    return ActivationValidationResult(
        ready_for_review=len(blockers) == 0,
        blockers=blockers,
        warnings=warnings,
    )


def activation_manifest_path(repo_root: Path, activation_id: str) -> Path:
    return repo_root / "runtime" / "dispatch" / "codex_activation" / f"{activation_id}.json"