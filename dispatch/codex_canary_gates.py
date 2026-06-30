"""Layered Codex canary execution gates — pure evaluation, no subprocess."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dispatch.codex_activation import validate_activation_manifest
from dispatch.codex_adapter import load_codex_restricted_adapter
from dispatch.codex_canary_contract import compute_canary_contract_hash
from dispatch.codex_cli_compatibility import evaluate_cli_compatibility
from dispatch.execution_gate import adapter_supports_execution

ACTIVATION_MARKER_ENV = "AGENTIC_OS_CODEX_ACTIVATION_AUTHORIZED"
EMERGENCY_DISABLE_FLAG = "runtime/dispatch/codex_emergency_disable.json"
CANARY_RUN_COUNTER = "runtime/dispatch/codex_canary_run_count.json"


@dataclass
class CanaryGateResult:
    allowed: bool
    blocked_reasons: list[str] = field(default_factory=list)
    gate_results: dict[str, bool] = field(default_factory=dict)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def evaluate_canary_execution_gates(
    repo_root: Path,
    *,
    registry_adapter: dict[str, Any],
    dedicated_adapter: dict[str, Any] | None = None,
    execute_flag: bool = False,
    activation_manifest: dict[str, Any] | None = None,
    human_approval: dict[str, Any] | None = None,
    cli_compatibility: dict[str, Any] | None = None,
    allocation_record: dict[str, Any] | None = None,
    activation_marker: str | None = None,
    reviewed_sha: str | None = None,
) -> CanaryGateResult:
    """Evaluate all canary gates; refuses before Codex subprocess when any gate fails."""
    blocked: list[str] = []
    gates: dict[str, bool] = {}

    dedicated = dedicated_adapter or load_codex_restricted_adapter(repo_root)

    marker = activation_marker or ""
    gates["activation_marker"] = marker == "phase3-activation-authorized"
    if not gates["activation_marker"]:
        blocked.append("missing explicit future activation marker")

    gates["supports_execution"] = adapter_supports_execution(registry_adapter)
    if not gates["supports_execution"]:
        blocked.append("codex-restricted supports_execution=false")

    promotion = str(dedicated.get("promotion_state", ""))
    gates["promotion_state"] = promotion in {"restricted_candidate", "restricted_execution", "active"}
    if not gates["promotion_state"]:
        blocked.append(f"promotion_state {promotion!r} incompatible with canary")

    if activation_manifest is None:
        blocked.append("missing reviewed activation manifest")
        gates["activation_manifest"] = False
    else:
        manifest_result = validate_activation_manifest(
            activation_manifest,
            repo_root=repo_root,
            current_reviewed_sha=reviewed_sha,
            cli_help_hash=str(activation_manifest.get("cli_help_hash", "")) or None,
        )
        gates["activation_manifest"] = manifest_result.ready_for_review
        if not manifest_result.ready_for_review:
            blocked.extend(manifest_result.blockers)

    gates["human_approval"] = bool(
        human_approval
        and not human_approval.get("revoked")
        and human_approval.get("adapter_id") == "codex-restricted"
        and human_approval.get("signature")
    )
    if not gates["human_approval"]:
        blocked.append("missing or invalid human approval record")

    if cli_compatibility is None:
        gates["cli_compatibility"] = False
        blocked.append("CLI compatibility record not supplied")
    else:
        compat = evaluate_cli_compatibility(
            {
                "version_text": cli_compatibility.get("version_raw", ""),
                "executable_path": cli_compatibility.get("executable_path", ""),
                "non_interactive_subcommand": "exec",
                "invocations": [],
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
        blocked.append("valid worktree allocation record required")

    expected_canary_hash = compute_canary_contract_hash()
    manifest_canary_hash = str((activation_manifest or {}).get("canary_contract_hash", ""))
    gates["canary_contract"] = manifest_canary_hash == expected_canary_hash
    if not gates["canary_contract"]:
        blocked.append("canary contract hash mismatch")

    gates["operator_execute_flag"] = execute_flag
    if not execute_flag:
        blocked.append("missing --execute-canary operator flag")

    counter_path = repo_root / CANARY_RUN_COUNTER
    counter = _load_json(counter_path) or {"count": 0}
    max_runs = int((activation_manifest or {}).get("maximum_runs", 1) or 1)
    gates["maximum_runs"] = int(counter.get("count", 0) or 0) < max_runs
    if not gates["maximum_runs"]:
        blocked.append("maximum canary run count exceeded")

    replay_claimed = bool(human_approval and human_approval.get("consumed"))
    gates["anti_replay"] = not replay_claimed
    if replay_claimed:
        blocked.append("human approval already consumed (anti-replay)")

    emergency_path = repo_root / EMERGENCY_DISABLE_FLAG
    emergency = _load_json(emergency_path)
    gates["emergency_disable"] = not (emergency and emergency.get("disabled"))
    if emergency and emergency.get("disabled"):
        blocked.append("emergency disable flag is set")

    return CanaryGateResult(
        allowed=len(blocked) == 0,
        blocked_reasons=blocked,
        gate_results=gates,
    )