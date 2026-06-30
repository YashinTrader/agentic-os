"""Phase 3.7B Codex canary preflight — package preparation only; no live execution."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from dispatch.agent_context_bundle import build_context_bundle, compute_bundle_hash
from dispatch.codex_activation import (
    activation_bundle_dir,
    build_activation_manifest_v2,
    compute_adapter_config_hash,
    compute_policy_hashes,
    utc_now,
)
from dispatch.codex_activation_gate import (
    PHASE3_7B_BLOCKED_REASON,
    evaluate_activation_gates,
    phase3_7b_authorization_path,
)
from dispatch.codex_adapter import build_codex_command, compute_command_contract_hash, load_codex_restricted_adapter
from dispatch.codex_canary_contract import (
    CANARY_FIXED_SENTENCE,
    FORBIDDEN_CANARY_OPERATIONS,
    build_canary_contract,
    build_canary_contract_body,
    compute_canary_contract_hash,
    expected_canary_relative_path,
)
from dispatch.execution_route_policy import (
    DEDICATED_CANARY_RUNNER_REASON,
    ROUTE_CODEX_CANARY,
    ROUTE_GENERIC_DISPATCH,
    evaluate_execution_route,
)
from dispatch.freshness import compute_preview_hash

PHASE37B_TASK_ID = "T-PHASE3-7B-CODEX-CANARY"
PHASE37B_DEFAULT_ACTIVATION_ID = "activation-phase37b-preflight"
PHASE37B_MAX_TIMEOUT_SECONDS = 600
PHASE37B_APPROVAL_EXPIRY_MINUTES = 30
AUTHORIZATION_TEMPLATE_FILENAME = "phase3_7b_authorization.template.json"
AUTHORIZATION_LIVE_FILENAME = "phase3_7b_authorization.json"
PHASE37B_MANIFEST_STATUS = "awaiting_human_approval"
PHASE37B_REQUEST_STATUS = "awaiting_human_decision"
PHASE37B_TEMPLATE_STATUS = "awaiting_human_authorization"

VERIFICATION_COMMANDS = (
    "python scripts/validate.py",
    "python scripts/validate_codex_activation.py",
    "python scripts/verify_codex_canary_package.py",
)


@dataclass
class PreflightGateReport:
    blocked: bool
    blocked_reasons: list[str] = field(default_factory=list)
    gate_results: dict[str, bool] = field(default_factory=dict)
    codex_subprocess_invoked: bool = False
    approval_consumed: bool = False


def new_immutable_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"canary-{stamp}-{uuid4().hex[:8]}"


def build_canary_markdown_content(*, run_id: str, timestamp: str | None = None) -> str:
    ts = timestamp or utc_now()
    return "\n".join(
        [
            "# Codex Canary",
            "",
            f"Run ID: {run_id}",
            f"Timestamp: {ts}",
            "",
            CANARY_FIXED_SENTENCE,
            "",
            "Allowed change:",
            "",
            "* exactly one new file matching the expected path.",
            "",
            "No other file may be created, modified, renamed, or deleted.",
            "",
            "Forbidden:",
            "",
            "* source files;",
            "* tests;",
            "* schemas;",
            "* scripts;",
            "* configuration;",
            "* dependency files;",
            "* ADRs;",
            "* task files;",
            "* workflows;",
            "* adapter registry;",
            "* existing documentation files;",
            "* Git commit;",
            "* Git merge;",
            "* Git push;",
            "* deployment;",
            "* production access;",
            "* MCP execution;",
            "* browser automation;",
            "* email;",
            "* package installation;",
            "* secret inspection;",
            "* shell commands unrelated to the bounded Codex process.",
            "",
            "Maximum execution time:",
            "",
            "10 minutes",
            "",
            "Maximum runs:",
            "",
            "1",
            "",
            "Automatic retry:",
            "",
            "false",
            "",
            "Worktree preservation:",
            "",
            "required",
            "",
            "Post-attempt suspension:",
            "",
            "required, whether successful, failed, or timed out.",
            "",
        ]
    )


def build_canary_contract_record(
    *,
    run_id: str,
    reviewed_commit_sha: str,
    cli_version: str,
    context_bundle_hash: str,
    expected_relative_path: str,
) -> dict[str, Any]:
    cmd_hash = compute_command_contract_hash()
    body = build_canary_contract_body(
        command_contract_hash=cmd_hash,
        context_bundle_hash=context_bundle_hash,
        cli_version=cli_version,
        reviewed_commit_sha=reviewed_commit_sha,
    )
    body["task_id"] = PHASE37B_TASK_ID
    body["maximum_timeout_seconds"] = PHASE37B_MAX_TIMEOUT_SECONDS
    body["documentation_only"] = True
    body["run_id"] = run_id
    body["expected_relative_path"] = expected_relative_path
    body["expected_content_hash"] = hashlib.sha256(
        build_canary_markdown_content(run_id=run_id, timestamp="CANONICAL").encode("utf-8")
    ).hexdigest()
    contract_hash = hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        **body,
        "contract_hash": contract_hash,
        "allowed_scope": [expected_relative_path],
        "forbidden_operations": sorted(FORBIDDEN_CANARY_OPERATIONS),
        "expected_diff": f"add {expected_relative_path}",
        "verification_commands": list(VERIFICATION_COMMANDS),
        "automatic_retry": False,
        "worktree_preservation_required": True,
        "post_attempt_suspension_required": True,
    }


def build_authorization_template(
    *,
    activation_id: str,
    task_id: str,
    run_id: str,
    reviewed_commit_sha: str,
    canary_contract_hash: str,
    context_bundle_hash: str,
    preview_hash: str,
    worktree_allocation_id: str,
    expected_file: str,
) -> dict[str, Any]:
    return {
        "authorization_id": f"auth-template-{activation_id}",
        "activation_id": activation_id,
        "task_id": task_id,
        "run_id": run_id,
        "reviewed_commit_sha": reviewed_commit_sha,
        "adapter_id": "codex-restricted",
        "canary_contract_hash": canary_contract_hash,
        "context_bundle_hash": context_bundle_hash,
        "preview_hash": preview_hash,
        "worktree_allocation_id": worktree_allocation_id,
        "expected_file": expected_file,
        "maximum_runs": 1,
        "timeout_seconds": PHASE37B_MAX_TIMEOUT_SECONDS,
        "human_approval_reference": None,
        "human_approval_signature_verified": False,
        "authorized_by": None,
        "authorized_at": None,
        "expires_at": None,
        "status": PHASE37B_TEMPLATE_STATUS,
        "statement": "Template only — not valid for live canary execution.",
    }


def build_phase37b_human_request(
    repo_root: Path,
    *,
    activation_id: str,
    reviewed_commit_sha: str,
    cli_version: str,
    context_bundle_hash: str,
    worktree_path: str,
    expected_file: str,
    run_id: str,
) -> dict[str, Any]:
    adapter = load_codex_restricted_adapter(repo_root)
    cmd_hash = compute_command_contract_hash()
    canary_hash = compute_canary_contract_hash(
        command_contract_hash=cmd_hash,
        context_bundle_hash=context_bundle_hash,
        cli_version=cli_version,
        reviewed_commit_sha=reviewed_commit_sha,
    )
    content_sample = build_canary_markdown_content(run_id=run_id)
    return {
        "request_id": f"request-{activation_id}",
        "activation_id": activation_id,
        "adapter_id": "codex-restricted",
        "task_id": PHASE37B_TASK_ID,
        "run_id": run_id,
        "reviewed_commit_sha": reviewed_commit_sha,
        "repository": str(repo_root),
        "canary_contract_hash": canary_hash,
        "command_contract_hash": cmd_hash,
        "context_bundle_hash": context_bundle_hash,
        "worktree_requirement": "allocated_isolated_worktree",
        "worktree_path": worktree_path,
        "expected_file": expected_file,
        "expected_content": content_sample,
        "maximum_runs": 1,
        "timeout_seconds": PHASE37B_MAX_TIMEOUT_SECONDS,
        "expected_network_usage": "Codex/OpenAI API via installed CLI (single bounded prompt)",
        "expected_cost_exposure": "possible Codex API token usage for one documentation-only canary",
        "allowed_file_change": expected_file,
        "forbidden_operations": sorted(FORBIDDEN_CANARY_OPERATIONS),
        "approval_expiry_minutes": PHASE37B_APPROVAL_EXPIRY_MINUTES,
        "approval_level_required": "human",
        "approver_type_required": "human",
        "requested_at": utc_now(),
        "status": PHASE37B_REQUEST_STATUS,
        "version": "1.1",
        "statement": "This request does not authorize execution.",
        "no_mcp": True,
        "no_merge_push": True,
        "no_deployment": True,
        "no_main_checkout_write": True,
        "failed_run_consumes_approval": True,
        "timed_out_run_consumes_approval": True,
        "artifacts_preserved": True,
        "post_attempt_suspension_required": True,
        "claude_post_run_review_required": True,
        "approval_policy": {
            "approval_level": str(adapter.get("approval_level", "human")),
            "phase3_7b_authorization_required": True,
        },
    }


def build_phase37b_manifest(
    repo_root: Path,
    *,
    activation_id: str,
    reviewed_commit_sha: str,
    cli_version: str,
    cli_help_hash: str,
    context_bundle_hash: str,
    worktree_allocation_id: str,
) -> dict[str, Any]:
    manifest = build_activation_manifest_v2(
        repo_root,
        activation_id=activation_id,
        reviewed_commit_sha=reviewed_commit_sha,
        cli_version=cli_version,
        cli_help_hash=cli_help_hash,
        context_bundle_hash=context_bundle_hash,
        status=PHASE37B_MANIFEST_STATUS,
    )
    manifest["task_id"] = PHASE37B_TASK_ID
    manifest["required_execution_route"] = ROUTE_CODEX_CANARY
    manifest["worktree_allocation_id"] = worktree_allocation_id
    manifest["automatic_disable_after_run"] = True
    manifest["post_attempt_suspension_required"] = True
    manifest["emergency_disable_active"] = False
    return manifest


def build_phase37b_preview(
    repo_root: Path,
    *,
    run_id: str,
    task_id: str,
    allocation_record: dict[str, Any],
    cli_compatibility: dict[str, Any],
    canary_contract: dict[str, Any],
    context_bundle_hash: str,
) -> dict[str, Any]:
    adapter = load_codex_restricted_adapter(repo_root)
    worktree_path = str(allocation_record.get("worktree_path", ""))
    base_sha = str(allocation_record.get("base_sha", ""))
    expected_file = str(canary_contract.get("expected_relative_path", ""))
    agent_output = str(Path(worktree_path) / "runtime" / "codex_agent_output.json")

    command_plan = build_codex_command(
        adapter,
        repo_root=repo_root,
        worktree_path=worktree_path,
        run_id=run_id,
        stdout_path=str(Path(worktree_path) / "stdout.log"),
        stderr_path=str(Path(worktree_path) / "stderr.log"),
        agent_output_path=agent_output,
        timeout_seconds=PHASE37B_MAX_TIMEOUT_SECONDS,
        cli_version=str(cli_compatibility.get("parsed_version") or cli_compatibility.get("version_raw", "")),
        allocation_record=allocation_record,
        task_id=task_id,
        base_sha=base_sha,
        scope_paths=["."],
        prompt=None,
    )

    preview = {
        "run_id": run_id,
        "task_id": task_id,
        "adapter_id": "codex-restricted",
        "command_argv": command_plan.argv,
        "codex_executable": str(cli_compatibility.get("executable_path", "")),
        "codex_version": str(cli_compatibility.get("parsed_version") or cli_compatibility.get("version_raw", "")),
        "cwd": worktree_path,
        "worktree_allocation_id": str(allocation_record.get("allocation_id", "")),
        "base_sha": base_sha,
        "output_path": agent_output,
        "expected_file": expected_file,
        "positional_prompt_hash": hashlib.sha256(
            (command_plan.argv[-1] if command_plan.argv else "").encode("utf-8")
        ).hexdigest(),
        "context_bundle_hash": context_bundle_hash,
        "canary_contract_hash": str(canary_contract.get("contract_hash", "")),
        "allowed_scope": [expected_file],
        "timeout_seconds": PHASE37B_MAX_TIMEOUT_SECONDS,
        "environment_variable_names": list(command_plan.environment_variable_names),
        "approval_level": "human",
        "required_execution_route": ROUTE_CODEX_CANARY,
        "maximum_runs": 1,
        "automatic_suspension": True,
        "automatic_retry": False,
        "dispatch_allowed": False,
        "handoff_path": f"handoffs/{task_id}__codex__to__claude.md",
        "command": " ".join(command_plan.argv),
        "working_directory": worktree_path,
        "scope_paths": ["."],
        "secrets_required": True,
        "worktree_required": True,
        "approval_gate": {"approval_level": "human", "approval_status": "pending_human"},
        "risk_gate": {"approval_level": "high", "risk_level": "high"},
        "plan_path": "runtime/orchestrator/latest_plan.json",
        "status": "prepared_not_executed",
        "blocked_reasons": list(command_plan.blocked_reasons),
    }
    preview["preview_hash"] = compute_preview_hash(preview, adapter=adapter)
    return preview


def build_context_bundle_for_preflight(
    repo_root: Path,
    *,
    run_id: str,
    worktree_path: str,
    base_sha: str,
    expected_file: str,
    preview: dict[str, Any],
) -> dict[str, Any]:
    task = {
        "id": PHASE37B_TASK_ID,
        "title": "Phase 3.7B documentation-only Codex canary",
        "objective": f"Create exactly one file: {expected_file}",
        "owner": "composer",
        "reviewer": "claude",
        "status": "ready",
        "phase": "3.7B",
        "risk_level": "high",
        "requires_human_approval": True,
    }
    plan = {
        "run_id": run_id,
        "task_id": PHASE37B_TASK_ID,
        "approval_level": "human",
        "approval_required": True,
    }
    adapter = json.loads(json.dumps(load_codex_restricted_adapter(repo_root), default=str))
    preview_copy = {
        **preview,
        "context_pack_excerpt": build_canary_markdown_content(run_id=run_id),
        "expected_file": expected_file,
        "exact_required_content": build_canary_markdown_content(run_id=run_id),
        "stop_after_one_file": True,
    }
    manifest = build_context_bundle(
        repo_root,
        run_id=run_id,
        task=task,
        plan=plan,
        preview=preview_copy,
        adapter_policy=adapter,
        worktree_path=worktree_path,
        base_sha=base_sha,
        allowed_paths=[expected_file],
        forbidden_operations=sorted(FORBIDDEN_CANARY_OPERATIONS),
        verification_commands=list(VERIFICATION_COMMANDS),
    )
    bundle_dir = repo_root / "runtime" / "dispatch" / "runs" / run_id / "codex_context"
    size_report = {
        "bundle_dir": str(bundle_dir),
        "bundle_hash": manifest.get("bundle_hash", ""),
        "total_bytes": sum(p.stat().st_size for p in bundle_dir.rglob("*") if p.is_file()),
        "file_count": len(list(bundle_dir.rglob("*"))),
        "environment_variable_names": list(adapter.get("env_vars_required") or []),
    }
    return {"manifest": manifest, "size_report": size_report, "bundle_hash": manifest.get("bundle_hash", "")}


def evaluate_preflight_gates(
    repo_root: Path,
    *,
    registry_adapter: dict[str, Any],
    dedicated_adapter: dict[str, Any],
    activation_manifest: dict[str, Any],
    cli_compatibility: dict[str, Any],
    allocation_record: dict[str, Any] | None,
    human_request: dict[str, Any],
) -> PreflightGateReport:
    generic_route = evaluate_execution_route(dedicated_adapter, ROUTE_GENERIC_DISPATCH)
    canary_route = evaluate_execution_route(dedicated_adapter, ROUTE_CODEX_CANARY)
    gate = evaluate_activation_gates(
        repo_root,
        registry_adapter=registry_adapter,
        dedicated_adapter=dedicated_adapter,
        activation_manifest=activation_manifest,
        human_approval=None,
        cli_compatibility=cli_compatibility,
        allocation_record=allocation_record,
        execute_flag=False,
        reviewed_sha=str(activation_manifest.get("reviewed_commit_sha", "")),
        activation_id=str(activation_manifest.get("activation_id", "")),
        require_phase3_7b=True,
    )
    blocked = list(gate.blocked_reasons)
    if generic_route.allowed:
        blocked.append("generic_dispatch must block codex-restricted")
    if not canary_route.allowed:
        blocked.extend(canary_route.reasons)
    if human_request.get("status") != PHASE37B_REQUEST_STATUS:
        blocked.append("human approval request must await_human_decision")
    if phase3_7b_authorization_path(
        repo_root, str(activation_manifest.get("activation_id", ""))
    ).exists():
        blocked.append("live phase3_7b_authorization.json must not exist during preflight")
    results = {
        **gate.gate_results,
        "generic_route_blocked": not generic_route.allowed,
        "dedicated_route_recognized": canary_route.allowed,
        "human_request_awaiting": human_request.get("status") == PHASE37B_REQUEST_STATUS,
        "phase3_7b_authorization_absent": not phase3_7b_authorization_path(
            repo_root, str(activation_manifest.get("activation_id", ""))
        ).exists(),
    }
    expected_blockers = {
        PHASE3_7B_BLOCKED_REASON,
        "missing or invalid human-signed approval",
        "missing --execute-canary operator flag",
    }
    has_expected = any(
        any(exp in reason for exp in expected_blockers) for reason in blocked
    )
    if not has_expected:
        blocked.append("preflight must remain blocked awaiting human approval and Phase 3.7B")
    return PreflightGateReport(
        blocked=True,
        blocked_reasons=sorted(set(blocked)),
        gate_results=results,
        codex_subprocess_invoked=False,
        approval_consumed=False,
    )


def build_live_command_preview(
    *,
    activation_id: str,
    run_id: str,
    allocation_id: str,
    approval_placeholder: str,
    authorization_placeholder: str,
) -> dict[str, str]:
    return {
        "canary_runner": (
            f"python scripts/run_codex_canary.py --execute-canary "
            f"--activation-id {activation_id} --manifest "
            f"runtime/dispatch/codex_activation/{activation_id}/activation_manifest.json "
            f"--allocation runtime/dispatch/codex_activation/{activation_id}/worktree_allocation.json "
            f"--approval {approval_placeholder} "
            f"--reviewed-sha <reviewed-sha>"
        ),
        "activation_id": activation_id,
        "run_id": run_id,
        "worktree_allocation_id": allocation_id,
        "human_approval_path_placeholder": approval_placeholder,
        "phase3_7b_authorization_path_placeholder": authorization_placeholder,
        "emergency_disable": (
            f"python scripts/disable_codex_canary.py --activation {activation_id} "
            f'--reason "operator emergency stop"'
        ),
        "note": "Do not run until Gabriel signs approval and Phase 3.7B authorization is recorded.",
    }


def allocation_record_to_gate_dict(record: Any) -> dict[str, Any]:
    from dispatch.worktree_registry import allocation_record_to_dict

    if isinstance(record, dict):
        return record
    return allocation_record_to_dict(record)


def validate_preflight_package(
    repo_root: Path,
    activation_id: str,
    *,
    reviewed_sha: str,
) -> list[str]:
    blockers: list[str] = []
    bundle = activation_bundle_dir(repo_root, activation_id)
    if not bundle.is_dir():
        return [f"missing activation bundle: {bundle}"]

    live_auth = bundle / AUTHORIZATION_LIVE_FILENAME
    if live_auth.exists():
        blockers.append("phase3_7b_authorization.json must not exist in preflight")

    template = bundle / AUTHORIZATION_TEMPLATE_FILENAME
    if not template.is_file():
        blockers.append("authorization template missing")
    else:
        data = json.loads(template.read_text(encoding="utf-8"))
        if data.get("status") != PHASE37B_TEMPLATE_STATUS:
            blockers.append("authorization template must be awaiting_human_authorization")
        if data.get("human_approval_reference"):
            blockers.append("template must not include human_approval_reference")

    request_path = bundle / "human_approval_request.json"
    if request_path.is_file():
        req = json.loads(request_path.read_text(encoding="utf-8"))
        if req.get("status") != PHASE37B_REQUEST_STATUS:
            blockers.append("human request status must be awaiting_human_decision")
        for forbidden in ("signature", "approved", "approval_hmac"):
            if forbidden in req:
                blockers.append(f"forbidden field in request: {forbidden}")

    manifest_path = bundle / "activation_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != PHASE37B_MANIFEST_STATUS:
            blockers.append("manifest status must be awaiting_human_approval")
        if manifest.get("runs_consumed", 0) != 0:
            blockers.append("runs_consumed must be 0")

    preflight_path = bundle / "preflight.json"
    if preflight_path.is_file():
        pre = json.loads(preflight_path.read_text(encoding="utf-8"))
        if pre.get("codex_subprocess_invoked"):
            blockers.append("codex_subprocess_invoked must be false")
        if pre.get("approval_consumed"):
            blockers.append("approval_consumed must be false")

    if str(reviewed_sha) and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("reviewed_commit_sha") != reviewed_sha:
            blockers.append("reviewed_commit_sha mismatch")

    return blockers