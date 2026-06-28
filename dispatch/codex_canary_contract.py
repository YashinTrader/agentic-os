"""Documentation-only Codex canary contract — deterministic hash, no execution."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CANARY_FILE_PATTERN = re.compile(r"^docs/codex-canary-[a-zA-Z0-9._-]+\.md$")
CANARY_FIXED_SENTENCE = "Codex documentation-only canary confirmed."
ALLOWED_CANARY_PATHS = ("docs/codex-canary-*.md",)

FORBIDDEN_CANARY_OPERATIONS = frozenset(
    {
        "modify_source",
        "modify_tests",
        "modify_dependencies",
        "modify_ci",
        "modify_adapter_config",
        "modify_task_protocol",
        "modify_approval_files",
        "delete_files",
        "git_commit",
        "git_merge",
        "git_push",
        "mcp_invoke",
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


@dataclass
class CanaryValidationResult:
    allowed: bool
    blocked_reasons: list[str] = field(default_factory=list)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_canary_contract() -> CanaryContract:
    body = {
        "version": "1.0",
        "allowed_path_glob": ALLOWED_CANARY_PATHS[0],
        "maximum_files_added": 1,
        "fixed_sentence": CANARY_FIXED_SENTENCE,
        "forbidden_operations": sorted(FORBIDDEN_CANARY_OPERATIONS),
        "documentation_only": True,
        "merge_allowed": False,
        "push_allowed": False,
    }
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()
    return CanaryContract(
        version=body["version"],
        allowed_path_glob=body["allowed_path_glob"],
        maximum_files_added=body["maximum_files_added"],
        fixed_sentence=body["fixed_sentence"],
        forbidden_operations=tuple(body["forbidden_operations"]),
        contract_hash=digest,
    )


def compute_canary_contract_hash() -> str:
    return build_canary_contract().contract_hash


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
            f"# Codex Canary {run_id}",
            "",
            f"- run_id: {run_id}",
            f"- timestamp: {ts}",
            "",
            CANARY_FIXED_SENTENCE,
            "",
        ]
    )


def validate_canary_audit_package(paths_present: dict[str, bool]) -> list[str]:
    """Validate future canary audit package completeness (no secret values)."""
    required = (
        "activation_manifest.json",
        "preview.json",
        "approval_record.json",
        "worktree_allocation.json",
        "result.json",
        "handoff.md",
    )
    blocked: list[str] = []
    for name in required:
        if not paths_present.get(name):
            blocked.append(f"missing audit artifact: {name}")
    return blocked