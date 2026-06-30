"""Codex canary activation gates — pure evaluation; Phase 3.7B required before subprocess."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dispatch.codex_adapter import compute_command_contract_hash, load_codex_restricted_adapter
from dispatch.codex_canary_contract import compute_canary_contract_hash
from dispatch.codex_cli_compatibility import evaluate_cli_compatibility
from dispatch.execution_gate import adapter_supports_execution
from dispatch.execution_route_policy import ROUTE_CODEX_CANARY, evaluate_execution_route

PHASE3_7B_AUTH_FILENAME = "phase3_7b_authorization.json"
DISABLED_FILENAME = "disabled.json"
ACTIVATION_MANIFEST_FILENAME = "activation_manifest.json"
PHASE3_7B_BLOCKED_REASON = "Phase 3.7B human authorization has not been recorded."

CANARY_COMPATIBLE_PROMOTION_STATES = frozenset(
    {"activation_candidate", "restricted_execution", "active"}
)
MANIFEST_LIVE_STATUSES = frozenset({"human_approved", "activation_ready"})
PHASE37A_PERMITTED_MANIFEST_STATUSES = frozenset(
    {"awaiting_claude_review", "awaiting_human_approval"}
)
FORBIDDEN_MANIFEST_STATUSES = frozenset(
    {"human_approved", "activation_ready", "active_canary_only", "active", "completed"}
)
SUSPENDED_MANIFEST_STATUSES = frozenset({"suspended", "revoked", "suspended_pending_review"})


@dataclass
class ActivationGateResult:
    allowed: bool
    blocked_reasons: list[str] = field(default_factory=list)
    gate_results: dict[str, bool] = field(default_factory=dict)
    stops_before_subprocess: bool = True


def activation_dir(repo_root: Path, activation_id: str) -> Path:
    return repo_root / "runtime" / "dispatch" / "codex_activation" / activation_id


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def phase3_7b_authorization_path(repo_root: Path, activation_id: str) -> Path:
    return activation_dir(repo_root, activation_id) / PHASE3_7B_AUTH_FILENAME


def disabled_path(repo_root: Path, activation_id: str) -> Path:
    return activation_dir(repo_root, activation_id) / DISABLED_FILENAME


def evaluate_phase3_7b_authorization(
    repo_root: Path,
    activation_id: str,
) -> tuple[bool, str]:
    path = phase3_7b_authorization_path(repo_root, activation_id)
    record = _load_json(path)
    if not record:
        return False, PHASE3_7B_BLOCKED_REASON
    if not record.get("authorized"):
        return False, PHASE3_7B_BLOCKED_REASON
    if not record.get("human_authorization_reference"):
        return False, PHASE3_7B_BLOCKED_REASON
    return True, ""


def evaluate_post_canary_suspension(
    *,
    runs_consumed: int,
    maximum_runs: int,
    attempt_status: str,
) -> dict[str, Any]:
    """Pure post-canary state transition (fixture/tests only in Phase 3.7A)."""
    exhausted = runs_consumed >= maximum_runs
    return {
        "runs_consumed": runs_consumed,
        "maximum_runs": maximum_runs,
        "activation_exhausted": exhausted,
        "status_after_attempt": "suspended_pending_review" if exhausted else "active_canary_only",
        "second_attempt_blocked": exhausted,
        "automatic_retry_allowed": False,
        "approval_remains_consumed": attempt_status in {"completed", "failed"},
        "supports_execution_config_unchanged": True,
    }


def evaluate_activation_gates(
    repo_root: Path,
    *,
    registry_adapter: dict[str, Any],
    dedicated_adapter: dict[str, Any] | None = None,
    activation_manifest: dict[str, Any] | None = None,
    human_approval: dict[str, Any] | None = None,
    cli_compatibility: dict[str, Any] | None = None,
    allocation_record: dict[str, Any] | None = None,
    execute_flag: bool = False,
    reviewed_sha: str | None = None,
    activation_id: str | None = None,
    require_phase3_7b: bool = True,
) -> ActivationGateResult:
    """Evaluate gates 1–15; Phase 3.7B blocks before subprocess (step 16)."""
    blocked: list[str] = []
    gates: dict[str, bool] = {}

    dedicated = dedicated_adapter or load_codex_restricted_adapter(repo_root)
    act_id = activation_id or str((activation_manifest or {}).get("activation_id", ""))

    route_decision = evaluate_execution_route(dedicated, ROUTE_CODEX_CANARY)
    gates["execution_route"] = route_decision.allowed
    if not route_decision.allowed:
        blocked.extend(route_decision.reasons)

    gates["supports_execution"] = adapter_supports_execution(registry_adapter)
    if not gates["supports_execution"]:
        blocked.append("codex-restricted supports_execution=false")

    promotion = str(dedicated.get("promotion_state", ""))
    gates["promotion_state"] = promotion in CANARY_COMPATIBLE_PROMOTION_STATES
    if not gates["promotion_state"]:
        blocked.append(f"promotion_state {promotion!r} not canary-compatible")

    if dedicated.get("execution_scope") not in (None, "canary_only"):
        gates["execution_scope"] = False
        blocked.append("execution_scope must be canary_only")
    else:
        gates["execution_scope"] = True

    if activation_manifest is None:
        gates["activation_manifest"] = False
        blocked.append("missing activation manifest")
    else:
        status = str(activation_manifest.get("status", ""))
        gates["manifest_status_live"] = status in MANIFEST_LIVE_STATUSES
        if status in FORBIDDEN_MANIFEST_STATUSES:
            blocked.append(f"manifest status {status!r} not permitted in Phase 3.7A")
        if status in SUSPENDED_MANIFEST_STATUSES:
            blocked.append(f"manifest suspended or revoked: {status}")
        gates["manifest_reviewed_commit"] = (
            not reviewed_sha
            or str(activation_manifest.get("reviewed_commit_sha", "")) == reviewed_sha
        )
        if reviewed_sha and not gates["manifest_reviewed_commit"]:
            blocked.append("manifest reviewed_commit_sha mismatch")

        cli_help = str(activation_manifest.get("cli_help_hash", ""))
        if cli_compatibility and cli_help:
            compat_help = str(cli_compatibility.get("help_hash", ""))
            gates["manifest_cli_hash"] = compat_help == cli_help or not compat_help
            if compat_help and cli_help != compat_help:
                blocked.append("cli_help_hash drift")

        gates["manifest_canary_hash"] = (
            str(activation_manifest.get("canary_contract_hash", "")) == compute_canary_contract_hash()
        )
        if not gates["manifest_canary_hash"]:
            blocked.append("canary_contract_hash mismatch")

        gates["manifest_command_hash"] = (
            str(activation_manifest.get("command_contract_hash", "")) == compute_command_contract_hash()
        )
        if not gates["manifest_command_hash"]:
            blocked.append("command_contract_hash mismatch")

    gates["human_approval_present"] = bool(
        human_approval
        and human_approval.get("signature")
        and human_approval.get("adapter_id") == "codex-restricted"
        and not human_approval.get("revoked")
    )
    if not gates["human_approval_present"]:
        blocked.append("missing or invalid human-signed approval")

    if human_approval and human_approval.get("consumed"):
        gates["anti_replay"] = False
        blocked.append("human approval already consumed")
    else:
        gates["anti_replay"] = True

    if cli_compatibility is None:
        gates["cli_compatibility"] = False
        blocked.append("CLI compatibility record not supplied")
    else:
        compat = evaluate_cli_compatibility(
            {
                "version_text": cli_compatibility.get("version_raw", ""),
                "executable_path": cli_compatibility.get("executable_path", ""),
                "non_interactive_subcommand": "exec",
                "invocations": cli_compatibility.get("invocations") or [],
            },
            require_installed=bool(cli_compatibility.get("executable_path")),
        )
        gates["cli_compatibility"] = compat.compatible
        if not compat.compatible:
            blocked.extend(compat.incompatibility_reasons or ["CLI incompatible"])

    gates["worktree"] = bool(
        allocation_record
        and allocation_record.get("worktree_path")
        and allocation_record.get("allocation_id")
    )
    if not gates["worktree"]:
        blocked.append("valid worktree allocation required")

    gates["operator_execute_flag"] = execute_flag
    if not execute_flag:
        blocked.append("missing --execute-canary operator flag")

    if act_id:
        disabled = _load_json(disabled_path(repo_root, act_id))
        gates["emergency_disable"] = not (disabled and disabled.get("disabled"))
        if disabled and disabled.get("disabled"):
            blocked.append("emergency disable flag set")
    else:
        gates["emergency_disable"] = True

    runs_consumed = int((activation_manifest or {}).get("runs_consumed", 0) or 0)
    max_runs = int((activation_manifest or {}).get("maximum_runs", 1) or 1)
    gates["maximum_runs"] = runs_consumed < max_runs
    if not gates["maximum_runs"]:
        blocked.append("maximum run count exhausted")

    claude_ref = str((activation_manifest or {}).get("claude_review_reference", "")).strip()
    gates["claude_review_reference"] = bool(claude_ref)
    if not claude_ref:
        blocked.append("missing Claude review reference")

    human_ref = str((activation_manifest or {}).get("human_approval_reference", "")).strip()
    gates["human_approval_reference"] = bool(human_ref)
    if not human_ref:
        blocked.append("missing human approval reference")

    if require_phase3_7b and act_id:
        ok, reason = evaluate_phase3_7b_authorization(repo_root, act_id)
        gates["phase3_7b_authorization"] = ok
        if not ok:
            blocked.append(reason)
    else:
        gates["phase3_7b_authorization"] = False
        blocked.append(PHASE3_7B_BLOCKED_REASON)

    return ActivationGateResult(
        allowed=len(blocked) == 0,
        blocked_reasons=blocked,
        gate_results=gates,
        stops_before_subprocess=True,
    )