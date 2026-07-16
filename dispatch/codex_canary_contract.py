"""Codex canary contract v2 — deterministic hash, one-file worktree canary."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CANARY_CONTRACT_VERSION = "2.0"
CANARY_FILE_PATTERN = re.compile(r"^docs/codex-canary-[a-zA-Z0-9._-]+\.md$")
CANARY_FIXED_SENTENCE = (
    "Codex restricted adapter canary completed inside an isolated worktree."
)
ALLOWED_CANARY_PATHS = ("docs/codex-canary-*.md",)
DEFAULT_TASK_ID = "T-PHASE3-7A-CODEX-CANARY-ACTIVATION"
DEFAULT_MAXIMUM_TIMEOUT_SECONDS = 900

FORBIDDEN_CANARY_OPERATIONS = frozenset(
    {
        "modify_existing_file",
        "modify_source",
        "modify_tests",
        "modify_dependencies",
        "modify_ci",
        "modify_adapter_config",
        "modify_adrs",
        "modify_task_protocol",
        "modify_approval_files",
        "delete_files",
        "git_commit",
        "git_merge",
        "git_push",
        "deploy",
        "production_access",
        "mcp_invoke",
        "browser_automation",
        "email_side_effects",
        "unrelated_shell",
    }
)


@dataclass
class CanaryContract:
    version: str
    allowed_path_glob: str
    maximum_files_added: int
    fixed_sentence: str
    forbidden_operations: tuple[str, ...]
    contract_hash: str
    task_id: str
    adapter_id: str
    maximum_runs: int
    approval_required: bool
    maximum_timeout_seconds: int


@dataclass
class CanaryValidationResult:
    allowed: bool
    blocked_reasons: list[str] = field(default_factory=list)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_canary_contract_body(
    *,
    command_contract_hash: str,
    context_bundle_hash: str = "",
    cli_version: str = "",
    reviewed_commit_sha: str = "",
) -> dict[str, Any]:
    return {
        "version": CANARY_CONTRACT_VERSION,
        "task_id": DEFAULT_TASK_ID,
        "adapter_id": "codex-restricted",
        "allowed_path_glob": ALLOWED_CANARY_PATHS[0],
        "maximum_files_added": 1,
        "fixed_sentence": CANARY_FIXED_SENTENCE,
        "forbidden_operations": sorted(FORBIDDEN_CANARY_OPERATIONS),
        "maximum_runs": 1,
        "approval_required": True,
        "maximum_timeout_seconds": DEFAULT_MAXIMUM_TIMEOUT_SECONDS,
        "command_contract_hash": command_contract_hash,
        "context_bundle_hash": context_bundle_hash,
        "cli_version": cli_version,
        "reviewed_commit_sha": reviewed_commit_sha,
        "documentation_only": False,
        "merge_allowed": False,
        "push_allowed": False,
    }


def build_canary_contract(
    *,
    command_contract_hash: str = "",
    context_bundle_hash: str = "",
    cli_version: str = "",
    reviewed_commit_sha: str = "",
) -> CanaryContract:
    from dispatch.codex_adapter import compute_command_contract_hash

    cmd_hash = command_contract_hash or compute_command_contract_hash()
    body = build_canary_contract_body(
        command_contract_hash=cmd_hash,
        context_bundle_hash=context_bundle_hash,
        cli_version=cli_version,
        reviewed_commit_sha=reviewed_commit_sha,
    )
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()
    return CanaryContract(
        version=body["version"],
        allowed_path_glob=body["allowed_path_glob"],
        maximum_files_added=body["maximum_files_added"],
        fixed_sentence=body["fixed_sentence"],
        forbidden_operations=tuple(body["forbidden_operations"]),
        contract_hash=digest,
        task_id=body["task_id"],
        adapter_id=body["adapter_id"],
        maximum_runs=body["maximum_runs"],
        approval_required=body["approval_required"],
        maximum_timeout_seconds=body["maximum_timeout_seconds"],
    )


def compute_canary_contract_hash(
    *,
    command_contract_hash: str = "",
    context_bundle_hash: str = "",
    cli_version: str = "",
    reviewed_commit_sha: str = "",
) -> str:
    return build_canary_contract(
        command_contract_hash=command_contract_hash,
        context_bundle_hash=context_bundle_hash,
        cli_version=cli_version,
        reviewed_commit_sha=reviewed_commit_sha,
    ).contract_hash


def expected_canary_relative_path(run_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", run_id.strip()).strip("-")[:60]
    return f"docs/codex-canary-{safe}.md"


def validate_canary_path(relative_path: str) -> list[str]:
    blocked: list[str] = []
    if not CANARY_FILE_PATTERN.match(relative_path.replace("\\", "/")):
        blocked.append(f"canary path not allowed: {relative_path!r}")
    return blocked


def validate_canary_file_changes(
    *,
    added_paths: list[str],
    modified_paths: list[str],
    deleted_paths: list[str],
) -> CanaryValidationResult:
    blocked: list[str] = []
    contract = build_canary_contract()

    if deleted_paths:
        blocked.append("canary forbids file deletions")
    if modified_paths:
        blocked.append("canary forbids modifying existing tracked files")
    if len(added_paths) != contract.maximum_files_added:
        blocked.append(
            f"canary requires exactly {contract.maximum_files_added} added file; "
            f"got {len(added_paths)}"
        )
    for path in added_paths:
        blocked.extend(validate_canary_path(path))

    return CanaryValidationResult(allowed=len(blocked) == 0, blocked_reasons=blocked)


def build_canary_file_content(*, run_id: str, timestamp: str | None = None) -> str:
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
        ]
    )


def validate_canary_audit_package(paths_present: dict[str, bool]) -> list[str]:
    required = (
        "activation_manifest.json",
        "preflight.json",
        "human_approval_request.json",
        "worktree_allocation.json",
        "result.json",
        "handoff.md",
    )
    blocked: list[str] = []
    for name in required:
        if not paths_present.get(name):
            blocked.append(f"missing audit artifact: {name}")
    return blocked