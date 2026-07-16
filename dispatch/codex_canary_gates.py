"""Layered Codex canary gates — delegates to codex_activation_gate (Phase 3.7A)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dispatch.codex_activation_gate import (
    PHASE3_7B_BLOCKED_REASON,
    ActivationGateResult,
    evaluate_activation_gates,
)

ACTIVATION_MARKER_ENV = "AGENTIC_OS_CODEX_ACTIVATION_AUTHORIZED"
EMERGENCY_DISABLE_FLAG = "runtime/dispatch/codex_emergency_disable.json"
CANARY_RUN_COUNTER = "runtime/dispatch/codex_canary_run_count.json"


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
) -> ActivationGateResult:
    """Backward-compatible wrapper; always requires Phase 3.7B authorization."""
    activation_id = str((activation_manifest or {}).get("activation_id", ""))
    return evaluate_activation_gates(
        repo_root,
        registry_adapter=registry_adapter,
        dedicated_adapter=dedicated_adapter,
        activation_manifest=activation_manifest,
        human_approval=human_approval,
        cli_compatibility=cli_compatibility,
        allocation_record=allocation_record,
        execute_flag=execute_flag,
        reviewed_sha=reviewed_sha,
        activation_id=activation_id or None,
        require_phase3_7b=True,
    )


__all__ = [
    "ACTIVATION_MARKER_ENV",
    "CANARY_RUN_COUNTER",
    "EMERGENCY_DISABLE_FLAG",
    "ActivationGateResult",
    "PHASE3_7B_BLOCKED_REASON",
    "evaluate_activation_gates",
    "evaluate_canary_execution_gates",
]