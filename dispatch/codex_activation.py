"""Codex activation manifest and human approval request — no live activation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dispatch.codex_adapter import compute_command_contract_hash, load_codex_restricted_adapter
from dispatch.codex_canary_contract import compute_canary_contract_hash
from dispatch.codex_activation_gate import (
    FORBIDDEN_MANIFEST_STATUSES,
    PHASE37A_PERMITTED_MANIFEST_STATUSES,
    PHASE37B_PERMITTED_MANIFEST_STATUSES,
)

ACTIVATION_MANIFEST_VERSION = "2.0"
HUMAN_REQUEST_VERSION = "1.0"

REQUIRED_MANIFEST_V2_FIELDS = (
    "activation_id",
    "version",
    "adapter_id",
    "adapter_config_hash",
    "promotion_state",
    "supports_execution",
    "execution_scope",
    "maximum_runs",
    "runs_consumed",
    "reviewed_commit_sha",
    "cli_version",
    "cli_help_hash",
    "command_contract_hash",
    "canary_contract_hash",
    "context_bundle_hash",
    "worktree_policy_hash",
    "environment_policy_hash",
    "approval_policy_hash",
    "emergency_disable_policy_hash",
    "human_approval_required",
    "human_approval_reference",
    "claude_review_required",
    "claude_review_reference",
    "phase3_7b_authorization_required",
    "phase3_7b_authorization_reference",
    "created_at",
    "expires_at",
    "status",
    "disabled_reason",
)

REQUIRED_HUMAN_REQUEST_FIELDS = (
    "request_id",
    "activation_id",
    "adapter_id",
    "reviewed_commit_sha",
    "canary_contract_hash",
    "command_contract_hash",
    "context_bundle_hash",
    "worktree_requirement",
    "maximum_runs",
    "timeout_seconds",
    "expected_network_usage",
    "expected_cost_exposure",
    "allowed_file_change",
    "forbidden_operations",
    "approval_expiry_minutes",
    "approval_level_required",
    "approver_type_required",
    "requested_at",
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
    emergency = {"phase3_7b_required": True, "automatic_disable_after_run": True}
    return {
        "worktree_policy_hash": _sha256_text(json.dumps(worktree, sort_keys=True)),
        "environment_policy_hash": _sha256_text(json.dumps(environment, sort_keys=True)),
        "approval_policy_hash": _sha256_text(json.dumps(approval, sort_keys=True)),
        "emergency_disable_policy_hash": _sha256_text(json.dumps(emergency, sort_keys=True)),
    }


def activation_bundle_dir(repo_root: Path, activation_id: str) -> Path:
    return repo_root / "runtime" / "dispatch" / "codex_activation" / activation_id


def build_activation_manifest_v2(
    repo_root: Path,
    *,
    activation_id: str,
    reviewed_commit_sha: str,
    cli_version: str,
    cli_help_hash: str,
    context_bundle_hash: str = "",
    status: str = "awaiting_claude_review",
) -> dict[str, Any]:
    adapter = load_codex_restricted_adapter(repo_root)
    policies = compute_policy_hashes(adapter)
    cmd_hash = compute_command_contract_hash()
    canary_hash = compute_canary_contract_hash(
        command_contract_hash=cmd_hash,
        context_bundle_hash=context_bundle_hash,
        cli_version=cli_version,
        reviewed_commit_sha=reviewed_commit_sha,
    )
    return {
        "activation_id": activation_id,
        "version": ACTIVATION_MANIFEST_VERSION,
        "adapter_id": "codex-restricted",
        "adapter_config_hash": compute_adapter_config_hash(adapter),
        "promotion_state": adapter.get("promotion_state", "activation_candidate"),
        "supports_execution": bool(adapter.get("supports_execution")),
        "execution_scope": adapter.get("execution_scope", "canary_only"),
        "maximum_runs": int(adapter.get("maximum_runs", 1) or 1),
        "runs_consumed": 0,
        "reviewed_commit_sha": reviewed_commit_sha,
        "cli_version": cli_version,
        "cli_help_hash": cli_help_hash,
        "command_contract_hash": cmd_hash,
        "canary_contract_hash": canary_hash,
        "context_bundle_hash": context_bundle_hash,
        "worktree_policy_hash": policies["worktree_policy_hash"],
        "environment_policy_hash": policies["environment_policy_hash"],
        "approval_policy_hash": policies["approval_policy_hash"],
        "emergency_disable_policy_hash": policies["emergency_disable_policy_hash"],
        "human_approval_required": True,
        "human_approval_reference": "",
        "claude_review_required": True,
        "claude_review_reference": "",
        "phase3_7b_authorization_required": True,
        "phase3_7b_authorization_reference": "",
        "created_at": utc_now(),
        "expires_at": "2099-01-01T00:00:00Z",
        "status": status,
        "disabled_reason": "",
        "live_run_authorized": False,
    }


def build_human_approval_request(
    repo_root: Path,
    *,
    activation_id: str,
    reviewed_commit_sha: str,
    context_bundle_hash: str = "",
    cli_version: str = "",
) -> dict[str, Any]:
    from dispatch.codex_canary_contract import (
        ALLOWED_CANARY_PATHS,
        FORBIDDEN_CANARY_OPERATIONS,
        build_canary_contract,
    )

    adapter = load_codex_restricted_adapter(repo_root)
    cmd_hash = compute_command_contract_hash()
    canary_hash = compute_canary_contract_hash(
        command_contract_hash=cmd_hash,
        context_bundle_hash=context_bundle_hash,
        cli_version=cli_version,
        reviewed_commit_sha=reviewed_commit_sha,
    )
    contract = build_canary_contract(command_contract_hash=cmd_hash)
    return {
        "request_id": f"request-{activation_id}",
        "activation_id": activation_id,
        "adapter_id": "codex-restricted",
        "reviewed_commit_sha": reviewed_commit_sha,
        "canary_contract_hash": canary_hash,
        "command_contract_hash": cmd_hash,
        "context_bundle_hash": context_bundle_hash,
        "worktree_requirement": "allocated_isolated_worktree",
        "maximum_runs": 1,
        "timeout_seconds": int(adapter.get("timeout_seconds", 600)),
        "expected_network_usage": "Codex/OpenAI API via installed CLI",
        "expected_cost_exposure": "single bounded canary prompt",
        "allowed_file_change": ALLOWED_CANARY_PATHS[0],
        "forbidden_operations": sorted(FORBIDDEN_CANARY_OPERATIONS),
        "approval_expiry_minutes": 15,
        "approval_level_required": "human",
        "approver_type_required": "human",
        "requested_at": utc_now(),
        "status": "awaiting_human_decision",
        "version": HUMAN_REQUEST_VERSION,
        "statement": "This request does not itself authorize execution.",
    }


def validate_activation_manifest_v2(
    manifest: dict[str, Any],
    *,
    repo_root: Path,
    current_reviewed_sha: str | None = None,
    cli_help_hash: str | None = None,
    phase: str = "3.7A",
    now: datetime | None = None,
) -> ActivationValidationResult:
    blockers: list[str] = []
    warnings: list[str] = []

    for field_name in REQUIRED_MANIFEST_V2_FIELDS:
        if field_name not in manifest:
            blockers.append(f"manifest missing field: {field_name}")

    status = str(manifest.get("status", ""))
    if phase == "3.7A":
        if status in FORBIDDEN_MANIFEST_STATUSES:
            blockers.append(f"manifest status {status!r} forbidden in Phase 3.7A")
        if status and status not in PHASE37A_PERMITTED_MANIFEST_STATUSES:
            if status not in FORBIDDEN_MANIFEST_STATUSES:
                blockers.append(f"manifest status {status!r} not permitted in Phase 3.7A")
    elif phase == "3.7B":
        if status in FORBIDDEN_MANIFEST_STATUSES:
            blockers.append(f"manifest status {status!r} forbidden in Phase 3.7B preflight")
        if status and status not in PHASE37B_PERMITTED_MANIFEST_STATUSES:
            if status not in FORBIDDEN_MANIFEST_STATUSES:
                blockers.append(f"manifest status {status!r} not permitted in Phase 3.7B preflight")

    if manifest.get("adapter_id") != "codex-restricted":
        blockers.append("adapter_id must be codex-restricted")
    if manifest.get("execution_scope") != "canary_only":
        blockers.append("execution_scope must be canary_only")
    if int(manifest.get("maximum_runs", 0) or 0) != 1:
        blockers.append("maximum_runs must equal 1")
    if not manifest.get("human_approval_required"):
        blockers.append("human_approval_required must be true")
    if not manifest.get("phase3_7b_authorization_required"):
        blockers.append("phase3_7b_authorization_required must be true")
    if manifest.get("live_run_authorized"):
        blockers.append(f"live_run_authorized must be false in Phase {phase}")

    if str(manifest.get("human_approval_reference", "")).strip():
        blockers.append(f"fabricated human_approval_reference not allowed in Phase {phase}")
    if phase == "3.7A" and str(manifest.get("claude_review_reference", "")).strip():
        blockers.append("fabricated claude_review_reference not allowed in Phase 3.7A")
    if str(manifest.get("phase3_7b_authorization_reference", "")).strip():
        blockers.append(f"fabricated phase3_7b_authorization_reference not allowed in Phase {phase}")

    try:
        adapter = load_codex_restricted_adapter(repo_root)
    except (OSError, ValueError) as exc:
        blockers.append(f"adapter config unavailable: {exc}")
        adapter = {}

    if adapter:
        expected_config_hash = compute_adapter_config_hash(adapter)
        if str(manifest.get("adapter_config_hash", "")) != expected_config_hash:
            blockers.append("adapter_config_hash does not match current candidate config")
        if phase == "3.7A" and not adapter.get("supports_execution"):
            blockers.append("adapter supports_execution must be true for activation candidate")
        if adapter.get("promotion_state") != "activation_candidate":
            blockers.append("promotion_state must be activation_candidate")

    expected_cmd_hash = compute_command_contract_hash()
    if str(manifest.get("command_contract_hash", "")) != expected_cmd_hash:
        blockers.append("command_contract_hash does not match current command contract")

    if phase != "3.7B":
        expected_canary_hash = compute_canary_contract_hash(
            command_contract_hash=expected_cmd_hash,
            context_bundle_hash=str(manifest.get("context_bundle_hash", "")),
            cli_version=str(manifest.get("cli_version", "")),
            reviewed_commit_sha=str(manifest.get("reviewed_commit_sha", "")),
        )
        if str(manifest.get("canary_contract_hash", "")) != expected_canary_hash:
            blockers.append("canary_contract_hash does not match current canary contract")
    elif not str(manifest.get("canary_contract_hash", "")).strip():
        blockers.append("canary_contract_hash required in Phase 3.7B preflight manifest")

    if current_reviewed_sha and str(manifest.get("reviewed_commit_sha", "")) != current_reviewed_sha:
        blockers.append("reviewed_commit_sha does not match current reviewed commit")

    if cli_help_hash and str(manifest.get("cli_help_hash", "")) != cli_help_hash:
        blockers.append("cli_help_hash does not match current CLI help")

    expires_raw = str(manifest.get("expires_at", ""))
    if expires_raw:
        try:
            expires = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
            ref = now or datetime.now(timezone.utc)
            if ref > expires:
                blockers.append("activation manifest expired")
        except ValueError:
            blockers.append("expires_at malformed")

    return ActivationValidationResult(
        ready_for_review=len(blockers) == 0,
        blockers=blockers,
        warnings=warnings,
    )


def validate_human_approval_request(request: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for field_name in REQUIRED_HUMAN_REQUEST_FIELDS:
        if field_name not in request:
            blockers.append(f"request missing field: {field_name}")
    if request.get("status") != "awaiting_human_decision":
        blockers.append("status must be awaiting_human_decision")
    for forbidden in ("signature", "approved", "approval_hmac", "human_approval_key"):
        if forbidden in request:
            blockers.append(f"forbidden field in request: {forbidden}")
    if request.get("approved") is True:
        blockers.append("approved must not be true in request package")
    return blockers


# Backward-compatible aliases for Phase 3.6 imports
def build_draft_activation_manifest(repo_root: Path, **kwargs: Any) -> dict[str, Any]:
    kwargs.pop("base_sha", None)
    kwargs.setdefault("status", "awaiting_claude_review")
    return build_activation_manifest_v2(repo_root, **kwargs)


def validate_activation_manifest(manifest: dict[str, Any], **kwargs: Any) -> ActivationValidationResult:
    if "phase" not in kwargs:
        version = str(manifest.get("version", "2.0"))
        kwargs["phase"] = "3.7A" if version == "2.0" else "3.6"
    return validate_activation_manifest_v2(manifest, **kwargs)


def activation_manifest_path(repo_root: Path, activation_id: str) -> Path:
    return activation_bundle_dir(repo_root, activation_id) / "activation_manifest.json"