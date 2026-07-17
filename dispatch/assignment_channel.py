"""File-based Claude ↔ Grok Build assignment channel (inbox/outbox/claims).

Phase 3.8B activates the full bounded contract + claim lifecycle for manual
pickup. No network, no merge/push, no automatic execution.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from dispatch.atomic_io import atomic_create_json, atomic_write_json
from dispatch.mcp_isolation import (
    extract_required_mcp_servers,
    normalize_required_mcp_servers,
    validate_required_mcp_servers,
)

ASSIGNMENT_SCHEMA_VERSION = "1.0"
INBOX_DIRNAME = "inbox"
OUTBOX_DIRNAME = "outbox"
CLAIM_DIRNAME = "claims"
INGEST_DIRNAME = "ingest"
EVENT_DIRNAME = "events"
REASSIGNMENT_DIRNAME = "reassignments"

# Lifecycle: pending -> claimed -> building -> awaiting_review -> terminal
# changes_requested is non-terminal rework: re-claimable for one correction cycle.
AssignmentStatus = Literal[
    "pending",
    "claimed",
    "building",
    "awaiting_review",
    "reviewable_failure",
    "accepted",
    "changes_requested",
    "rejected",
    "cancelled",
    "superseded",
]
OutboxStatus = Literal[
    "completed",
    "failed",
    "blocked",
    "awaiting_review",
    "accepted",
    "changes_requested",
    "rejected",
]
ResolutionVerb = Literal["accepted", "changes_requested", "rejected"]

ACTIVE_PICKABLE_STATUSES = frozenset({"pending", "changes_requested"})
CLAIMED_OR_BEYOND = frozenset(
    {
        "claimed",
        "building",
        "awaiting_review",
        "accepted",
        "rejected",
    }
)
TERMINAL_STATUSES = frozenset({"accepted", "rejected", "cancelled", "superseded"})
RESOLVABLE_FROM_STATUSES = frozenset({"awaiting_review"})
RESOLUTION_REQUIRES_NOTE = frozenset({"changes_requested", "rejected"})

# Task YAML status mapping used by the bridge
TASK_STATUS_ON_CLAIM = "in_progress"
TASK_STATUS_ON_COMPLETE = "review"
TASK_STATUS_READY = "ready"

REQUIRED_ASSIGNMENT_FIELDS = frozenset(
    {
        "schema_version",
        "assignment_id",
        "task_id",
        "title",
        "goal",
        "base_branch",
        "base_sha",
        "new_branch",
        "allowed_paths",
        "forbidden_operations",
        "acceptance_criteria",
        "verification_commands",
        "timeout",
        "handoff_path",
        "assigned_by",
        "assigned_to",
        "created_at",
        "status",
    }
)

# Backward-compatible aliases still accepted when present
LEGACY_OPTIONAL_FIELDS = frozenset(
    {
        "adapter_id",
        "execution_route",
        "task_path",
        "handoff_rel",
        "instructions",
        "updated_at",
    }
)

REQUIRED_OUTBOX_FIELDS = frozenset(
    {
        "schema_version",
        "assignment_id",
        "task_id",
        "adapter_id",
        "status",
        "finished_at",
    }
)

VALID_ASSIGNMENT_STATUSES = frozenset(
    {
        "pending",
        "claimed",
        "building",
        "awaiting_review",
        "reviewable_failure",
        "accepted",
        "changes_requested",
        "rejected",
        "cancelled",
        "superseded",
    }
)
VALID_OUTBOX_STATUSES = frozenset(
    {
        "completed",
        "failed",
        "blocked",
        "awaiting_review",
        "accepted",
        "changes_requested",
        "rejected",
    }
)

DEFAULT_FORBIDDEN_OPERATIONS = [
    "git_push_to_protected",
    "git_merge",
    "deploy",
    "production_access",
    "mcp_execution",
    "secrets_exfiltration",
]

DEFAULT_ADAPTER_ID = "composer-restricted"
DEFAULT_EXECUTION_ROUTE = "composer_local_builder"
DEFAULT_ASSIGNED_TO = "composer"
DEFAULT_TIMEOUT_SECONDS = 1800

REASSIGNMENT_REASONS = frozenset(
    {
        "unavailable",
        "quota_exhausted",
        "authentication_failed",
        "timeout",
        "operator_requested",
    }
)


@dataclass(frozen=True)
class BuilderProfile:
    agent_id: str
    adapter_id: str
    execution_route: str


BUILTIN_BUILDER_PROFILES = {
    "composer": BuilderProfile("composer", "composer-restricted", "composer_local_builder"),
    "grok": BuilderProfile("composer", "composer-restricted", "composer_local_builder"),
    "codex": BuilderProfile("codex", "codex-restricted", "codex_local_builder"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def assignments_root(repo_root: Path) -> Path:
    return repo_root / "runtime" / "dispatch" / "assignments"


def inbox_dir(repo_root: Path) -> Path:
    return assignments_root(repo_root) / INBOX_DIRNAME


def outbox_dir(repo_root: Path) -> Path:
    return assignments_root(repo_root) / OUTBOX_DIRNAME


def claims_dir(repo_root: Path) -> Path:
    return assignments_root(repo_root) / CLAIM_DIRNAME


def ingest_dir(repo_root: Path) -> Path:
    return assignments_root(repo_root) / INGEST_DIRNAME


def events_dir(repo_root: Path) -> Path:
    return assignments_root(repo_root) / EVENT_DIRNAME


def reassignments_dir(repo_root: Path) -> Path:
    return assignments_root(repo_root) / REASSIGNMENT_DIRNAME


def generate_assignment_id(task_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:8]
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", task_id.strip()).strip("-")[:24]
    return f"assign-{stamp}-{safe}-{suffix}"


def resolve_builder_profile(
    repo_root: Path,
    agent_id: str,
) -> tuple[BuilderProfile | None, list[str]]:
    """Resolve a builder alias or an adapter-registry agent id."""
    requested = agent_id.strip().lower()
    if requested in BUILTIN_BUILDER_PROFILES:
        return BUILTIN_BUILDER_PROFILES[requested], []

    registry_path = repo_root / "agents" / "adapter_registry.yaml"
    if registry_path.is_file():
        try:
            import yaml

            registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            return None, [f"failed to read adapter registry: {exc}"]
        adapters = registry.get("adapters", []) if isinstance(registry, dict) else []
        for adapter in adapters:
            if not isinstance(adapter, dict):
                continue
            if str(adapter.get("agent_id", "")).strip().lower() != requested:
                continue
            adapter_id = str(adapter.get("id") or "").strip()
            route = str(adapter.get("required_execution_route") or "").strip()
            if not adapter_id or not route:
                continue
            if str(adapter.get("status") or "active").lower() == "disabled":
                return None, [f"builder {agent_id!r} has only disabled adapters"]
            return BuilderProfile(requested, adapter_id, route), []
    return None, [f"no assignment adapter registered for builder {agent_id!r}"]


@dataclass
class AssignmentRecord:
    assignment_id: str
    task_id: str
    title: str
    goal: str
    base_branch: str
    base_sha: str
    new_branch: str
    allowed_paths: list[str]
    forbidden_operations: list[str]
    acceptance_criteria: list[str]
    verification_commands: list[str]
    timeout: int
    handoff_path: str
    assigned_by: str
    assigned_to: str
    created_at: str
    status: str
    adapter_id: str = DEFAULT_ADAPTER_ID
    execution_route: str = DEFAULT_EXECUTION_ROUTE
    task_path: str = ""
    updated_at: str = ""
    instructions: str | None = None
    claimed_at: str | None = None
    claimed_by: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    resolution_note: str | None = None
    correction_note: str | None = None
    reassigned_from: str | None = None
    reassignment_reason: str | None = None
    reassigned_to_assignment_id: str | None = None
    wake_requested: bool = False
    wake_delivered: bool = False
    woken_at: str | None = None
    wake_state: str = "not_requested"
    wake_detail: str | None = None
    required_mcp_servers: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    source_path: str = ""

    # Legacy alias used by dashboard/index code
    @property
    def handoff_rel(self) -> str:
        return self.handoff_path


@dataclass
class OutboxRecord:
    assignment_id: str
    task_id: str
    adapter_id: str
    status: str
    finished_at: str
    run_id: str | None = None
    handoff_path: str | None = None
    branch_tip_sha: str | None = None
    branch_name: str | None = None
    blocked_reasons: list[str] = field(default_factory=list)
    result_summary: str | None = None
    claim_path: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    resolution_note: str | None = None
    parse_errors: list[str] = field(default_factory=list)
    source_path: str = ""


@dataclass
class ClaimRecord:
    assignment_id: str
    task_id: str
    claimed_by: str
    claimed_at: str
    status: str
    source_path: str = ""


def _load_json_file(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    if not path.is_file():
        return None, [f"{path}: file does not exist"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"{path}: malformed JSON: {exc}"]
    if not isinstance(data, dict):
        return None, [f"{path}: root must be a JSON object"]
    return data, errors


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _as_int(value: Any, default: int = DEFAULT_TIMEOUT_SECONDS) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_required_mcp_servers(value: Any) -> list[str]:
    if value is None:
        return []
    try:
        return normalize_required_mcp_servers(value)
    except TypeError:
        return []


def validate_assignment_payload(data: dict[str, Any]) -> list[str]:
    """Schema-validate a full assignment contract. Non-fatal for readers."""
    errors: list[str] = []
    # Allow handoff_rel as legacy alias for handoff_path
    if "handoff_path" not in data and data.get("handoff_rel"):
        data = {**data, "handoff_path": data["handoff_rel"]}

    missing = sorted(REQUIRED_ASSIGNMENT_FIELDS - set(data.keys()))
    if missing:
        errors.append(f"missing required fields: {', '.join(missing)}")
    if str(data.get("schema_version", "")) != ASSIGNMENT_SCHEMA_VERSION:
        errors.append(f"schema_version must be {ASSIGNMENT_SCHEMA_VERSION!r}")
    status = str(data.get("status", ""))
    if status and status not in VALID_ASSIGNMENT_STATUSES:
        errors.append(f"invalid assignment status: {status!r}")
    if "adapter_id" in data and not str(data.get("adapter_id") or "").strip():
        errors.append("adapter_id must be non-empty")
    if "execution_route" in data and not str(data.get("execution_route") or "").strip():
        errors.append("execution_route must be non-empty")
    assigned_to = str(data.get("assigned_to") or "").strip().lower()
    profile = BUILTIN_BUILDER_PROFILES.get(assigned_to)
    if profile:
        if data.get("adapter_id") and str(data.get("adapter_id")) != profile.adapter_id:
            errors.append(
                f"adapter_id must be {profile.adapter_id} for builder {profile.agent_id}"
            )
        if data.get("execution_route") and str(data.get("execution_route")) != profile.execution_route:
            errors.append(
                f"execution_route must be {profile.execution_route} for builder {profile.agent_id}"
            )
    for list_field in (
        "allowed_paths",
        "forbidden_operations",
        "acceptance_criteria",
        "verification_commands",
    ):
        if list_field in data and data[list_field] is not None:
            if not isinstance(data[list_field], list):
                errors.append(f"{list_field} must be a list")
    if "required_mcp_servers" in data and data["required_mcp_servers"] is not None:
        errors.extend(validate_required_mcp_servers(data["required_mcp_servers"]))
    if "timeout" in data and data["timeout"] is not None:
        try:
            timeout = int(data["timeout"])
            if timeout <= 0:
                errors.append("timeout must be a positive integer")
        except (TypeError, ValueError):
            errors.append("timeout must be an integer")
    return errors


# Backward-compatible name used by Phase 3.8 tests/dashboard
def validate_inbox_payload(data: dict[str, Any]) -> list[str]:
    """Validate inbox payloads. Accepts full contract or legacy Phase 3.8 shape."""
    # If full contract fields are present, use full validator.
    if "title" in data and "goal" in data and "base_branch" in data:
        return validate_assignment_payload(data)

    # Legacy minimal schema (Phase 3.8 preview)
    errors: list[str] = []
    legacy_required = frozenset(
        {
            "schema_version",
            "assignment_id",
            "task_id",
            "adapter_id",
            "assigned_by",
            "assigned_to",
            "status",
            "created_at",
            "execution_route",
            "task_path",
            "handoff_rel",
        }
    )
    missing = sorted(legacy_required - set(data.keys()))
    if missing:
        # Prefer reporting against full contract when clearly incomplete
        if not missing or "title" not in data:
            full_missing = sorted(
                REQUIRED_ASSIGNMENT_FIELDS
                - set(data.keys())
                - {"handoff_path"}  # may use handoff_rel
            )
            if "handoff_path" not in data and "handoff_rel" not in data:
                full_missing.append("handoff_path")
            errors.append(f"missing required fields: {', '.join(sorted(set(full_missing)))}")
        else:
            errors.append(f"missing required fields: {', '.join(missing)}")
    if str(data.get("schema_version", "")) != ASSIGNMENT_SCHEMA_VERSION:
        errors.append(f"schema_version must be {ASSIGNMENT_SCHEMA_VERSION!r}")
    status = str(data.get("status", ""))
    if status and status not in VALID_ASSIGNMENT_STATUSES:
        errors.append(f"invalid inbox status: {status!r}")
    if not str(data.get("adapter_id") or "").strip():
        errors.append("adapter_id must be non-empty")
    if not str(data.get("execution_route") or "").strip():
        errors.append("execution_route must be non-empty")
    return errors


def validate_outbox_payload(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_OUTBOX_FIELDS - set(data))
    if missing:
        errors.append(f"missing required fields: {', '.join(missing)}")
    if str(data.get("schema_version", "")) != ASSIGNMENT_SCHEMA_VERSION:
        errors.append(f"schema_version must be {ASSIGNMENT_SCHEMA_VERSION!r}")
    status = str(data.get("status", ""))
    if status and status not in VALID_OUTBOX_STATUSES:
        errors.append(f"invalid outbox status: {status!r}")
    return errors


def parse_assignment_record(data: dict[str, Any], *, source_path: str = "") -> AssignmentRecord:
    # Normalize handoff_path from legacy handoff_rel
    handoff = str(data.get("handoff_path") or data.get("handoff_rel") or "")
    errors = validate_inbox_payload(data)
    timeout_raw = data.get("timeout", DEFAULT_TIMEOUT_SECONDS)
    return AssignmentRecord(
        assignment_id=str(data.get("assignment_id") or ""),
        task_id=str(data.get("task_id") or ""),
        title=str(data.get("title") or ""),
        goal=str(data.get("goal") or data.get("instructions") or ""),
        base_branch=str(data.get("base_branch") or ""),
        base_sha=str(data.get("base_sha") or "") or "",
        new_branch=str(data.get("new_branch") or ""),
        allowed_paths=_as_str_list(data.get("allowed_paths")),
        forbidden_operations=_as_str_list(data.get("forbidden_operations"))
        or list(DEFAULT_FORBIDDEN_OPERATIONS),
        acceptance_criteria=_as_str_list(data.get("acceptance_criteria")),
        verification_commands=_as_str_list(data.get("verification_commands")),
        timeout=_as_int(timeout_raw),
        handoff_path=handoff,
        assigned_by=str(data.get("assigned_by") or ""),
        assigned_to=str(data.get("assigned_to") or DEFAULT_ASSIGNED_TO),
        created_at=str(data.get("created_at") or ""),
        status=str(data.get("status") or "unknown"),
        adapter_id=str(data.get("adapter_id") or DEFAULT_ADAPTER_ID),
        execution_route=str(data.get("execution_route") or DEFAULT_EXECUTION_ROUTE),
        task_path=str(data.get("task_path") or ""),
        updated_at=str(data.get("updated_at") or data.get("created_at") or ""),
        instructions=str(data.get("instructions") or "") or None,
        claimed_at=str(data.get("claimed_at") or "") or None,
        claimed_by=str(data.get("claimed_by") or "") or None,
        reviewed_by=str(data.get("reviewed_by") or "") or None,
        reviewed_at=str(data.get("reviewed_at") or "") or None,
        resolution_note=str(data.get("resolution_note") or "") or None,
        correction_note=str(data.get("correction_note") or "") or None,
        reassigned_from=str(data.get("reassigned_from") or "") or None,
        reassignment_reason=str(data.get("reassignment_reason") or "") or None,
        reassigned_to_assignment_id=(
            str(data.get("reassigned_to_assignment_id") or "") or None
        ),
        wake_requested=bool(data.get("wake_requested", False)),
        wake_delivered=bool(data.get("wake_delivered", False)),
        woken_at=str(data.get("woken_at") or "") or None,
        wake_state=str(data.get("wake_state") or "not_requested"),
        wake_detail=str(data.get("wake_detail") or "") or None,
        required_mcp_servers=_safe_required_mcp_servers(data.get("required_mcp_servers")),
        parse_errors=errors,
        source_path=source_path,
    )


def parse_outbox_record(data: dict[str, Any], *, source_path: str = "") -> OutboxRecord:
    errors = validate_outbox_payload(data)
    blocked = data.get("blocked_reasons")
    return OutboxRecord(
        assignment_id=str(data.get("assignment_id") or ""),
        task_id=str(data.get("task_id") or ""),
        adapter_id=str(data.get("adapter_id") or ""),
        status=str(data.get("status") or "unknown"),
        finished_at=str(data.get("finished_at") or ""),
        run_id=str(data.get("run_id") or "") or None,
        handoff_path=str(data.get("handoff_path") or "") or None,
        branch_tip_sha=str(data.get("branch_tip_sha") or "") or None,
        branch_name=str(data.get("branch_name") or "") or None,
        blocked_reasons=list(blocked) if isinstance(blocked, list) else [],
        result_summary=str(data.get("result_summary") or "") or None,
        claim_path=str(data.get("claim_path") or "") or None,
        reviewed_by=str(data.get("reviewed_by") or "") or None,
        reviewed_at=str(data.get("reviewed_at") or "") or None,
        resolution_note=str(data.get("resolution_note") or "") or None,
        parse_errors=errors,
        source_path=source_path,
    )


def assignment_to_payload(record: AssignmentRecord) -> dict[str, Any]:
    payload = {
        "schema_version": ASSIGNMENT_SCHEMA_VERSION,
        "assignment_id": record.assignment_id,
        "task_id": record.task_id,
        "title": record.title,
        "goal": record.goal,
        "base_branch": record.base_branch,
        "base_sha": record.base_sha or None,
        "new_branch": record.new_branch,
        "allowed_paths": list(record.allowed_paths),
        "forbidden_operations": list(record.forbidden_operations),
        "acceptance_criteria": list(record.acceptance_criteria),
        "verification_commands": list(record.verification_commands),
        "timeout": int(record.timeout),
        "handoff_path": record.handoff_path,
        "assigned_by": record.assigned_by,
        "assigned_to": record.assigned_to,
        "created_at": record.created_at,
        "updated_at": record.updated_at or record.created_at,
        "status": record.status,
        "adapter_id": record.adapter_id,
        "execution_route": record.execution_route,
        "task_path": record.task_path,
        "instructions": record.instructions,
        "claimed_at": record.claimed_at,
        "claimed_by": record.claimed_by,
        "reviewed_by": record.reviewed_by,
        "reviewed_at": record.reviewed_at,
        "resolution_note": record.resolution_note,
        "correction_note": record.correction_note,
        "reassigned_from": record.reassigned_from,
        "reassignment_reason": record.reassignment_reason,
        "reassigned_to_assignment_id": record.reassigned_to_assignment_id,
        "wake_requested": record.wake_requested,
        "wake_delivered": record.wake_delivered,
        "woken_at": record.woken_at,
        "wake_state": record.wake_state,
        "wake_detail": record.wake_detail,
        "required_mcp_servers": list(record.required_mcp_servers or []),
        # Legacy alias for older readers
        "handoff_rel": record.handoff_path,
    }
    return payload


def write_assignment(
    repo_root: Path,
    *,
    task_id: str,
    title: str = "",
    goal: str = "",
    base_branch: str = "main",
    base_sha: str | None = None,
    new_branch: str = "",
    allowed_paths: list[str] | None = None,
    forbidden_operations: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    verification_commands: list[str] | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    handoff_path: str | None = None,
    assigned_by: str = "claude",
    assigned_to: str = DEFAULT_ASSIGNED_TO,
    wake: bool = False,
    task_path: str = "",
    instructions: str | None = None,
    assignment_id: str | None = None,
    status: str = "pending",
    adapter_id: str | None = None,
    execution_route: str | None = None,
    reassigned_from: str | None = None,
    reassignment_reason: str | None = None,
    required_mcp_servers: list[str] | None = None,
) -> tuple[Path | None, list[str]]:
    """Write a pending assignment to inbox. Schema-validates before write."""
    assigner = assigned_by.strip().lower()
    if wake and assigner != "claude":
        return None, ["only claude may create an assignment with wake requested"]
    assigner_profile = BUILTIN_BUILDER_PROFILES.get(assigner)
    if assigner_profile is not None:
        return None, [
            f"builder identity {assigner_profile.agent_id!r} may not create assignments; "
            "use an orchestrator identity"
        ]
    aid = assignment_id or generate_assignment_id(task_id)
    now = utc_now()
    profile, profile_errors = resolve_builder_profile(repo_root, assigned_to)
    if profile is None:
        return None, profile_errors
    canonical_assigned_to = profile.agent_id
    resolved_adapter = adapter_id or profile.adapter_id
    resolved_route = execution_route or profile.execution_route
    resolved_handoff = handoff_path or (
        f"handoffs/{task_id}__{canonical_assigned_to}__to__{assigned_by}.md"
    )
    resolved_branch = new_branch or f"agent/{canonical_assigned_to}/{task_id}"
    resolved_task_path = task_path or f"tasks/active/{task_id}.yaml"
    resolved_title = title or task_id
    resolved_goal = goal or instructions or f"Execute {task_id}"

    payload = {
        "schema_version": ASSIGNMENT_SCHEMA_VERSION,
        "assignment_id": aid,
        "task_id": task_id,
        "title": resolved_title,
        "goal": resolved_goal,
        "base_branch": base_branch,
        "base_sha": base_sha,
        "new_branch": resolved_branch,
        "allowed_paths": allowed_paths or [],
        "forbidden_operations": forbidden_operations or list(DEFAULT_FORBIDDEN_OPERATIONS),
        "acceptance_criteria": acceptance_criteria or [],
        "verification_commands": verification_commands or [],
        "timeout": int(timeout),
        "handoff_path": resolved_handoff,
        "handoff_rel": resolved_handoff,
        "assigned_by": assigned_by,
        "assigned_to": canonical_assigned_to,
        "created_at": now,
        "updated_at": now,
        "status": status,
        "adapter_id": resolved_adapter,
        "execution_route": resolved_route,
        "task_path": resolved_task_path,
        "instructions": instructions,
        "claimed_at": None,
        "claimed_by": None,
        "reassigned_from": reassigned_from,
        "reassignment_reason": reassignment_reason,
        "reassigned_to_assignment_id": None,
        "wake_requested": bool(wake),
        "wake_delivered": False,
        "woken_at": None,
        "wake_state": "pending_wake" if wake else "not_requested",
        "wake_detail": None,
        "required_mcp_servers": normalize_required_mcp_servers(
            required_mcp_servers if required_mcp_servers is not None else []
        ),
    }
    errors = validate_assignment_payload(payload)
    if errors:
        return None, errors

    target = inbox_dir(repo_root) / f"{aid}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target, payload)
    if wake:
        from dispatch.agent_wake import request_agent_wake

        outcome = request_agent_wake(
            repo_root, assignment_id=aid, task_id=task_id,
            agent_id=canonical_assigned_to, adapter_id=resolved_adapter,
            task_path=resolved_task_path, requested_by=assigned_by,
        )
        payload.update(
            wake_delivered=outcome.delivered, woken_at=outcome.woken_at,
            wake_state=outcome.state, wake_detail=outcome.detail,
        )
        atomic_write_json(target, payload)
    return target, []


def _write_inbox_record(repo_root: Path, record: AssignmentRecord) -> Path:
    target = inbox_dir(repo_root) / f"{record.assignment_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = assignment_to_payload(record)
    errors = validate_assignment_payload(payload)
    if errors:
        # Still write when updating known records, but surface via exception for safety
        raise ValueError(f"assignment schema invalid: {'; '.join(errors)}")
    atomic_write_json(target, payload)
    return target


def read_assignment(repo_root: Path, assignment_id: str) -> tuple[AssignmentRecord | None, list[str]]:
    path = inbox_dir(repo_root) / f"{assignment_id}.json"
    data, errors = _load_json_file(path)
    if data is None:
        return None, errors
    record = parse_assignment_record(data, source_path=str(path.relative_to(repo_root)).replace("\\", "/"))
    errors.extend(record.parse_errors)
    return record, errors


def list_inbox_assignments(repo_root: Path) -> tuple[list[AssignmentRecord], list[str]]:
    root = inbox_dir(repo_root)
    if not root.exists():
        return [], []
    if not root.is_dir():
        return [], [f"{root}: path exists but is not a directory"]

    records: list[AssignmentRecord] = []
    errors: list[str] = []
    for path in sorted(root.glob("*.json")):
        data, load_errors = _load_json_file(path)
        errors.extend(load_errors)
        rel = str(path.relative_to(repo_root)).replace("\\", "/")
        if data is None:
            records.append(
                AssignmentRecord(
                    assignment_id=path.stem,
                    task_id="",
                    title="",
                    goal="",
                    base_branch="",
                    base_sha="",
                    new_branch="",
                    allowed_paths=[],
                    forbidden_operations=[],
                    acceptance_criteria=[],
                    verification_commands=[],
                    timeout=DEFAULT_TIMEOUT_SECONDS,
                    handoff_path="",
                    assigned_by="",
                    assigned_to="",
                    created_at="",
                    status="unknown",
                    parse_errors=load_errors,
                    source_path=rel,
                )
            )
            continue
        record = parse_assignment_record(data, source_path=rel)
        errors.extend(record.parse_errors)
        records.append(record)
    return records, errors


def has_active_claim(repo_root: Path, assignment_id: str) -> bool:
    return (claims_dir(repo_root) / f"{assignment_id}.json").is_file()


def list_claims(repo_root: Path) -> tuple[list[ClaimRecord], list[str]]:
    root = claims_dir(repo_root)
    if not root.exists():
        return [], []
    if not root.is_dir():
        return [], [f"{root}: path exists but is not a directory"]
    records: list[ClaimRecord] = []
    errors: list[str] = []
    for path in sorted(root.glob("*.json")):
        data, load_errors = _load_json_file(path)
        errors.extend(load_errors)
        if data is None:
            continue
        records.append(
            ClaimRecord(
                assignment_id=str(data.get("assignment_id") or path.stem),
                task_id=str(data.get("task_id") or ""),
                claimed_by=str(data.get("claimed_by") or ""),
                claimed_at=str(data.get("claimed_at") or ""),
                status=str(data.get("status") or "claimed"),
                source_path=str(path.relative_to(repo_root)).replace("\\", "/"),
            )
        )
    return records, errors


def evaluate_assignment_pickability(
    repo_root: Path,
    record: AssignmentRecord,
) -> tuple[bool, str]:
    """Worker-eligibility discipline: only pending, unclaimed, non-terminal."""
    if record.parse_errors:
        return False, f"assignment has schema errors: {record.parse_errors[0]}"
    if record.status in TERMINAL_STATUSES:
        return False, f"assignment status {record.status!r} is terminal"
    if record.status in CLAIMED_OR_BEYOND:
        return False, f"assignment status {record.status!r} already claimed/completed"
    if record.status not in ACTIVE_PICKABLE_STATUSES:
        return False, f"assignment status {record.status!r} is not pickable"
    if has_active_claim(repo_root, record.assignment_id):
        return False, f"assignment {record.assignment_id} already has a claim file"
    outbox_path = outbox_dir(repo_root) / f"{record.assignment_id}.json"
    # changes_requested keeps a resolution outbox for ingest/dashboard but is
    # still re-claimable for one correction cycle (claim clears that outbox).
    if outbox_path.is_file() and record.status != "changes_requested":
        return False, f"assignment {record.assignment_id} already has an outbox result"
    return True, "eligible"


def list_pending_assignments(repo_root: Path) -> tuple[list[AssignmentRecord], list[str]]:
    records, errors = list_inbox_assignments(repo_root)
    pending: list[AssignmentRecord] = []
    for record in records:
        ok, _ = evaluate_assignment_pickability(repo_root, record)
        if ok:
            pending.append(record)
    return pending, errors


def claim_assignment(
    repo_root: Path,
    assignment_id: str,
    *,
    claimed_by: str | None = DEFAULT_ASSIGNED_TO,
    sync_task_yaml: bool = True,
) -> tuple[AssignmentRecord | None, list[str]]:
    """Atomically claim a pending assignment. Never re-claims."""
    errors: list[str] = []
    record, read_errors = read_assignment(repo_root, assignment_id)
    errors.extend(read_errors)
    if record is None:
        return None, errors

    claimant = (claimed_by or record.assigned_to).strip().lower()
    claimant_profile = BUILTIN_BUILDER_PROFILES.get(claimant)
    canonical_claimant = claimant_profile.agent_id if claimant_profile else claimant
    if canonical_claimant != record.assigned_to:
        errors.append(
            f"assignment is assigned to {record.assigned_to!r}; "
            f"builder {canonical_claimant!r} may not claim it"
        )
        return None, errors

    ok, reason = evaluate_assignment_pickability(repo_root, record)
    if not ok:
        errors.append(reason)
        return None, errors

    # Correction-cycle re-claim: drop prior resolution outbox so complete can rewrite it.
    if record.status == "changes_requested":
        _clear_outbox_file(repo_root, assignment_id)

    claim_path = claims_dir(repo_root) / f"{assignment_id}.json"
    claim_path.parent.mkdir(parents=True, exist_ok=True)
    now = utc_now()
    claim_payload = {
        "schema_version": ASSIGNMENT_SCHEMA_VERSION,
        "assignment_id": assignment_id,
        "task_id": record.task_id,
        "claimed_by": canonical_claimant,
        "claimed_at": now,
        "status": "claimed",
    }
    try:
        atomic_create_json(claim_path, claim_payload)
    except FileExistsError:
        errors.append(f"assignment {assignment_id} already claimed (atomic create failed)")
        return None, errors

    record.status = "claimed"
    record.claimed_at = now
    record.claimed_by = canonical_claimant
    record.updated_at = now
    try:
        _write_inbox_record(repo_root, record)
    except ValueError as exc:
        errors.append(str(exc))
        return record, errors

    if sync_task_yaml and record.task_id:
        sync_errors = sync_task_status_from_assignment(
            repo_root,
            task_id=record.task_id,
            assignment_status="claimed",
            task_path=record.task_path or None,
        )
        errors.extend(sync_errors)

    return record, errors


def set_assignment_status(
    repo_root: Path,
    assignment_id: str,
    status: str,
    *,
    sync_task_yaml: bool = True,
) -> tuple[AssignmentRecord | None, list[str]]:
    if status not in VALID_ASSIGNMENT_STATUSES:
        return None, [f"invalid status: {status!r}"]
    record, errors = read_assignment(repo_root, assignment_id)
    if record is None:
        return None, errors
    record.status = status
    record.updated_at = utc_now()
    try:
        _write_inbox_record(repo_root, record)
    except ValueError as exc:
        errors.append(str(exc))
        return record, errors
    if sync_task_yaml and record.task_id:
        errors.extend(
            sync_task_status_from_assignment(
                repo_root,
                task_id=record.task_id,
                assignment_status=status,
                task_path=record.task_path or None,
            )
        )
    return record, errors


def write_assignment_event(
    repo_root: Path,
    *,
    event_type: str,
    source: str,
    target: str,
    assignment_id: str,
    task_id: str,
    reason: str | None = None,
    message: str | None = None,
    previous_assignment_id: str | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Persist a notification event. Events never mutate assignment state."""
    now = utc_now()
    event_id = f"event-{uuid.uuid4().hex}"
    payload: dict[str, Any] = {
        "schema_version": ASSIGNMENT_SCHEMA_VERSION,
        "event_id": event_id,
        "event_type": event_type,
        "source": source,
        "target": target,
        "assignment_id": assignment_id,
        "task_id": task_id,
        "reason": reason,
        "message": message,
        "previous_assignment_id": previous_assignment_id,
        "wake_state": "notification_queued",
        "created_at": now,
        "consumed_at": None,
    }
    target_path = events_dir(repo_root) / f"{now.replace(':', '')}-{event_id}.json"
    try:
        atomic_create_json(target_path, payload)
    except (FileExistsError, OSError) as exc:
        return None, [f"failed to write assignment event: {exc}"]
    return payload, []


def list_assignment_events(repo_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    root = events_dir(repo_root)
    if not root.exists():
        return [], []
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted(root.glob("*.json")):
        payload, load_errors = _load_json_file(path)
        errors.extend(load_errors)
        if payload is not None:
            events.append(payload)
    return events, errors


def poke_assignment(
    repo_root: Path,
    assignment_id: str,
    *,
    actor: str,
    message: str | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Queue an orchestrator-to-assigned-builder notification."""
    record, errors = read_assignment(repo_root, assignment_id)
    if record is None:
        return None, errors
    if actor != record.assigned_by:
        errors.append(
            f"only assignment orchestrator {record.assigned_by!r} may poke this builder"
        )
        return None, errors
    if record.status != "pending":
        errors.append(f"only pending assignments may be poked; status is {record.status!r}")
        return None, errors
    return write_assignment_event(
        repo_root,
        event_type="assignment.poked",
        source=actor,
        target=record.assigned_to,
        assignment_id=record.assignment_id,
        task_id=record.task_id,
        message=message,
    )


def reassign_assignment(
    repo_root: Path,
    assignment_id: str,
    *,
    reassigned_by: str,
    assigned_to: str,
    reason: str,
    poke: bool = False,
    sync_task_yaml: bool = True,
) -> tuple[AssignmentRecord | None, list[str]]:
    """Supersede one assignment and create one pickable fallback assignment."""
    record, errors = read_assignment(repo_root, assignment_id)
    if record is None:
        return None, errors
    if reassigned_by != record.assigned_by:
        errors.append(
            f"only assignment orchestrator {record.assigned_by!r} may reassign this work"
        )
        return None, errors
    if reason not in REASSIGNMENT_REASONS:
        errors.append(f"invalid reassignment reason: {reason!r}")
        return None, errors
    if record.status in TERMINAL_STATUSES:
        errors.append(f"assignment status {record.status!r} cannot be reassigned")
        return None, errors

    profile, profile_errors = resolve_builder_profile(repo_root, assigned_to)
    errors.extend(profile_errors)
    if profile is None:
        return None, errors
    if profile.agent_id == record.assigned_to:
        errors.append(f"assignment is already assigned to {profile.agent_id!r}")
        return None, errors

    lock_path = reassignments_dir(repo_root) / f"{assignment_id}.json"
    lock_payload = {
        "schema_version": ASSIGNMENT_SCHEMA_VERSION,
        "assignment_id": assignment_id,
        "reassigned_by": reassigned_by,
        "assigned_to": profile.agent_id,
        "reason": reason,
        "created_at": utc_now(),
    }
    try:
        atomic_create_json(lock_path, lock_payload)
    except FileExistsError:
        return None, [f"assignment {assignment_id} already has a reassignment record"]
    except OSError as exc:
        return None, [f"failed to acquire reassignment lock: {exc}"]

    replacement_id = generate_assignment_id(record.task_id)
    replacement_path, create_errors = write_assignment(
        repo_root,
        task_id=record.task_id,
        title=record.title,
        goal=record.goal,
        base_branch=record.base_branch,
        base_sha=record.base_sha,
        allowed_paths=record.allowed_paths,
        forbidden_operations=record.forbidden_operations,
        acceptance_criteria=record.acceptance_criteria,
        verification_commands=record.verification_commands,
        timeout=record.timeout,
        assigned_by=record.assigned_by,
        assigned_to=profile.agent_id,
        task_path=record.task_path,
        instructions=record.instructions,
        assignment_id=replacement_id,
        adapter_id=profile.adapter_id,
        execution_route=profile.execution_route,
        reassigned_from=record.assignment_id,
        reassignment_reason=reason,
    )
    errors.extend(create_errors)
    if replacement_path is None:
        lock_path.unlink(missing_ok=True)
        return None, errors

    previous_status = record.status
    record.status = "superseded"
    record.updated_at = utc_now()
    record.reassigned_to_assignment_id = replacement_id
    record.reassignment_reason = reason
    try:
        _write_inbox_record(repo_root, record)
    except (OSError, ValueError) as exc:
        replacement_path.unlink(missing_ok=True)
        lock_path.unlink(missing_ok=True)
        return None, [f"failed to supersede original assignment: {exc}"]

    lock_payload["replacement_assignment_id"] = replacement_id
    lock_payload["previous_status"] = previous_status
    atomic_write_json(lock_path, lock_payload)

    if sync_task_yaml and record.task_id:
        errors.extend(
            sync_task_status_from_assignment(
                repo_root,
                task_id=record.task_id,
                assignment_status="pending",
                task_path=record.task_path or None,
            )
        )

    replacement, read_errors = read_assignment(repo_root, replacement_id)
    errors.extend(read_errors)
    if replacement is None:
        return None, errors
    if poke:
        _, event_errors = write_assignment_event(
            repo_root,
            event_type="assignment.reassigned",
            source=reassigned_by,
            target=replacement.assigned_to,
            assignment_id=replacement.assignment_id,
            task_id=replacement.task_id,
            reason=reason,
            previous_assignment_id=record.assignment_id,
        )
        errors.extend(event_errors)
    return replacement, errors


def write_outbox_result(
    repo_root: Path,
    *,
    assignment_id: str,
    task_id: str,
    status: str = "awaiting_review",
    handoff_path: str | None = None,
    branch_tip_sha: str | None = None,
    branch_name: str | None = None,
    blocked_reasons: list[str] | None = None,
    result_summary: str | None = None,
    run_id: str | None = None,
    claim_path: str | None = None,
    adapter_id: str = DEFAULT_ADAPTER_ID,
) -> tuple[Path | None, list[str]]:
    """Write result to outbox. Schema-validates on write."""
    payload = {
        "schema_version": ASSIGNMENT_SCHEMA_VERSION,
        "assignment_id": assignment_id,
        "task_id": task_id,
        "adapter_id": adapter_id,
        "status": status,
        "finished_at": utc_now(),
        "run_id": run_id,
        "handoff_path": handoff_path,
        "branch_tip_sha": branch_tip_sha,
        "branch_name": branch_name,
        "blocked_reasons": blocked_reasons or [],
        "result_summary": result_summary,
        "claim_path": claim_path
        or f"runtime/dispatch/assignments/claims/{assignment_id}.json",
    }
    errors = validate_outbox_payload(payload)
    if errors:
        return None, errors
    target = outbox_dir(repo_root) / f"{assignment_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target, payload)
    return target, []


def complete_assignment(
    repo_root: Path,
    assignment_id: str,
    *,
    handoff_path: str | None = None,
    branch_tip_sha: str | None = None,
    branch_name: str | None = None,
    result_summary: str | None = None,
    blocked_reasons: list[str] | None = None,
    outbox_status: str = "awaiting_review",
    sync_task_yaml: bool = True,
) -> tuple[OutboxRecord | None, list[str]]:
    """Mark assignment awaiting_review and write outbox result."""
    record, errors = read_assignment(repo_root, assignment_id)
    if record is None:
        return None, errors
    if record.status not in {"claimed", "building", "awaiting_review"}:
        errors.append(
            f"cannot complete assignment in status {record.status!r}; "
            "must be claimed|building|awaiting_review"
        )
        return None, errors
    was_awaiting_review = record.status == "awaiting_review"

    handoff = handoff_path or record.handoff_path
    out_path, out_errors = write_outbox_result(
        repo_root,
        assignment_id=assignment_id,
        task_id=record.task_id,
        status=outbox_status,
        handoff_path=handoff,
        branch_tip_sha=branch_tip_sha,
        branch_name=branch_name or record.new_branch,
        blocked_reasons=blocked_reasons,
        result_summary=result_summary,
        claim_path=f"runtime/dispatch/assignments/claims/{assignment_id}.json",
        adapter_id=record.adapter_id,
    )
    errors.extend(out_errors)
    if out_path is None:
        return None, errors

    record.status = "awaiting_review"
    record.updated_at = utc_now()
    try:
        _write_inbox_record(repo_root, record)
    except ValueError as exc:
        errors.append(str(exc))

    if sync_task_yaml and record.task_id:
        errors.extend(
            sync_task_status_from_assignment(
                repo_root,
                task_id=record.task_id,
                assignment_status="awaiting_review",
                task_path=record.task_path or None,
            )
        )

    out_record, read_errors = read_outbox_result(repo_root, assignment_id)
    errors.extend(read_errors)
    if not was_awaiting_review:
        from dispatch.orchestrator_pokes import write_orchestrator_poke

        _, poke_errors = write_orchestrator_poke(
            repo_root, source=record.assigned_to, assignment_id=record.assignment_id,
            task_id=record.task_id, event="assignment_completed",
        )
        errors.extend(poke_errors)
    return out_record, errors


def _clear_claim_file(repo_root: Path, assignment_id: str) -> None:
    claim_path = claims_dir(repo_root) / f"{assignment_id}.json"
    if claim_path.is_file():
        claim_path.unlink()


def _clear_outbox_file(repo_root: Path, assignment_id: str) -> None:
    out_path = outbox_dir(repo_root) / f"{assignment_id}.json"
    if out_path.is_file():
        out_path.unlink()


def _update_outbox_resolution(
    repo_root: Path,
    *,
    assignment_id: str,
    task_id: str,
    resolution: ResolutionVerb,
    reviewed_by: str,
    reviewed_at: str,
    resolution_note: str | None,
    adapter_id: str = DEFAULT_ADAPTER_ID,
) -> tuple[Path | None, list[str]]:
    """Merge resolution fields into existing outbox (or create a minimal one)."""
    existing, _ = read_outbox_result(repo_root, assignment_id)
    payload: dict[str, Any] = {
        "schema_version": ASSIGNMENT_SCHEMA_VERSION,
        "assignment_id": assignment_id,
        "task_id": task_id,
        "adapter_id": adapter_id,
        "status": resolution,
        "finished_at": existing.finished_at if existing else reviewed_at,
        "run_id": existing.run_id if existing else None,
        "handoff_path": existing.handoff_path if existing else None,
        "branch_tip_sha": existing.branch_tip_sha if existing else None,
        "branch_name": existing.branch_name if existing else None,
        "blocked_reasons": list(existing.blocked_reasons) if existing else [],
        "result_summary": existing.result_summary if existing else None,
        "claim_path": (
            existing.claim_path
            if existing
            else f"runtime/dispatch/assignments/claims/{assignment_id}.json"
        ),
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at,
        "resolution_note": resolution_note,
    }
    errors = validate_outbox_payload(payload)
    if errors:
        return None, errors
    target = outbox_dir(repo_root) / f"{assignment_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target, payload)
    return target, []


def resolve_assignment(
    repo_root: Path,
    assignment_id: str,
    *,
    resolution: ResolutionVerb,
    note: str | None = None,
    reviewed_by: str = "claude",
    sync_task_yaml: bool = True,
) -> tuple[AssignmentRecord | None, list[str]]:
    """Reviewer resolution: accept | request-changes | reject.

    - accepted: terminal; task YAML -> done
    - rejected: terminal; task YAML -> blocked; note required
    - changes_requested: non-terminal rework; note required; claim+outbox cleared
      so the assignment is re-claimable exactly once per correction cycle
    """
    errors: list[str] = []
    if resolution not in {"accepted", "changes_requested", "rejected"}:
        return None, [f"invalid resolution: {resolution!r}"]

    note_text = (note or "").strip() or None
    if resolution in RESOLUTION_REQUIRES_NOTE and not note_text:
        return None, [f"{resolution} requires a non-empty --note"]

    record, read_errors = read_assignment(repo_root, assignment_id)
    errors.extend(read_errors)
    if record is None:
        return None, errors

    if record.status not in RESOLVABLE_FROM_STATUSES:
        errors.append(
            f"cannot resolve assignment in status {record.status!r}; "
            "must be awaiting_review"
        )
        return None, errors

    now = utc_now()
    record.status = resolution
    record.updated_at = now
    record.reviewed_by = reviewed_by
    record.reviewed_at = now
    record.resolution_note = note_text
    if resolution == "changes_requested":
        record.correction_note = note_text
        # One re-claim cycle: release claim so pickability returns.
        # Keep outbox as a resolution record (status=changes_requested) for
        # ingest/dashboard; claim clears it for the next build cycle.
        _clear_claim_file(repo_root, assignment_id)
        record.claimed_at = None
        record.claimed_by = None

    out_path, out_errors = _update_outbox_resolution(
        repo_root,
        assignment_id=assignment_id,
        task_id=record.task_id,
        resolution=resolution,
        reviewed_by=reviewed_by,
        reviewed_at=now,
        resolution_note=note_text,
        adapter_id=record.adapter_id,
    )
    errors.extend(out_errors)
    if out_path is None and out_errors:
        return None, errors

    try:
        _write_inbox_record(repo_root, record)
    except ValueError as exc:
        errors.append(str(exc))
        return None, errors

    if sync_task_yaml and record.task_id:
        errors.extend(
            sync_task_status_from_assignment(
                repo_root,
                task_id=record.task_id,
                assignment_status=resolution,
                task_path=record.task_path or None,
            )
        )

    from dispatch.orchestrator_pokes import write_orchestrator_poke

    _, poke_errors = write_orchestrator_poke(
        repo_root, source=reviewed_by, assignment_id=record.assignment_id,
        task_id=record.task_id, event=f"assignment_{resolution}",
    )
    errors.extend(poke_errors)

    return record, errors


def accept_assignment(
    repo_root: Path,
    assignment_id: str,
    *,
    note: str | None = None,
    reviewed_by: str = "claude",
    sync_task_yaml: bool = True,
) -> tuple[AssignmentRecord | None, list[str]]:
    return resolve_assignment(
        repo_root,
        assignment_id,
        resolution="accepted",
        note=note,
        reviewed_by=reviewed_by,
        sync_task_yaml=sync_task_yaml,
    )


def request_changes_assignment(
    repo_root: Path,
    assignment_id: str,
    *,
    note: str,
    reviewed_by: str = "claude",
    sync_task_yaml: bool = True,
) -> tuple[AssignmentRecord | None, list[str]]:
    return resolve_assignment(
        repo_root,
        assignment_id,
        resolution="changes_requested",
        note=note,
        reviewed_by=reviewed_by,
        sync_task_yaml=sync_task_yaml,
    )


def reject_assignment(
    repo_root: Path,
    assignment_id: str,
    *,
    note: str,
    reviewed_by: str = "claude",
    sync_task_yaml: bool = True,
) -> tuple[AssignmentRecord | None, list[str]]:
    return resolve_assignment(
        repo_root,
        assignment_id,
        resolution="rejected",
        note=note,
        reviewed_by=reviewed_by,
        sync_task_yaml=sync_task_yaml,
    )


def read_outbox_result(repo_root: Path, assignment_id: str) -> tuple[OutboxRecord | None, list[str]]:
    path = outbox_dir(repo_root) / f"{assignment_id}.json"
    data, errors = _load_json_file(path)
    if data is None:
        return None, errors
    record = parse_outbox_record(
        data, source_path=str(path.relative_to(repo_root)).replace("\\", "/")
    )
    errors.extend(record.parse_errors)
    return record, errors


def list_outbox_results(repo_root: Path) -> tuple[list[OutboxRecord], list[str]]:
    root = outbox_dir(repo_root)
    if not root.exists():
        return [], []
    if not root.is_dir():
        return [], [f"{root}: path exists but is not a directory"]

    records: list[OutboxRecord] = []
    errors: list[str] = []
    for path in sorted(root.glob("*.json")):
        data, load_errors = _load_json_file(path)
        errors.extend(load_errors)
        rel = str(path.relative_to(repo_root)).replace("\\", "/")
        if data is None:
            records.append(
                OutboxRecord(
                    assignment_id=path.stem,
                    task_id="",
                    adapter_id="",
                    status="unknown",
                    finished_at="",
                    parse_errors=load_errors,
                    source_path=rel,
                )
            )
            continue
        record = parse_outbox_record(data, source_path=rel)
        errors.extend(record.parse_errors)
        records.append(record)
    return records, errors


def ingest_handoff_from_outbox(repo_root: Path, assignment_id: str) -> tuple[str | None, list[str]]:
    """Read-only: resolve handoff path from outbox record if present."""
    record, errors = read_outbox_result(repo_root, assignment_id)
    if record is None:
        return None, errors
    if record.handoff_path:
        return record.handoff_path, errors
    if errors:
        return None, errors
    return None, [f"outbox {assignment_id}: handoff_path not set"]


def ingest_outbox_results(repo_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Reviewer-side ingest: index outbox results, link handoffs/branches, write ingest log.

    Pure file operations. Does not merge or push.
    """
    outbox_records, errors = list_outbox_results(repo_root)
    inbox_records, inbox_errors = list_inbox_assignments(repo_root)
    errors.extend(inbox_errors)
    inbox_by_id = {r.assignment_id: r for r in inbox_records}

    ingested: list[dict[str, Any]] = []
    now = utc_now()
    for out in outbox_records:
        inbox = inbox_by_id.get(out.assignment_id)
        handoff = out.handoff_path
        handoff_exists = False
        if handoff:
            handoff_exists = (repo_root / handoff).is_file()
        entry = {
            "assignment_id": out.assignment_id,
            "task_id": out.task_id,
            "outbox_status": out.status,
            "assignment_status": inbox.status if inbox else None,
            "handoff_path": handoff,
            "handoff_exists": handoff_exists,
            "branch_name": out.branch_name or (inbox.new_branch if inbox else None),
            "branch_tip_sha": out.branch_tip_sha,
            "result_summary": out.result_summary,
            "reviewed_by": out.reviewed_by
            or (inbox.reviewed_by if inbox else None),
            "reviewed_at": out.reviewed_at
            or (inbox.reviewed_at if inbox else None),
            "resolution_note": out.resolution_note
            or (inbox.resolution_note if inbox else None),
            "outbox_path": out.source_path,
            "inbox_path": inbox.source_path if inbox else None,
            "ingested_at": now,
        }
        # Promote inbox to awaiting_review if still claimed/building
        if inbox and inbox.status in {"claimed", "building"}:
            set_assignment_status(
                repo_root,
                out.assignment_id,
                "awaiting_review",
                sync_task_yaml=True,
            )
            entry["assignment_status"] = "awaiting_review"
        ingested.append(entry)

    ingest_path = ingest_dir(repo_root) / "latest_ingest.json"
    ingest_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        ingest_path,
        {
            "schema_version": ASSIGNMENT_SCHEMA_VERSION,
            "ingested_at": now,
            "count": len(ingested),
            "results": ingested,
        },
    )
    return ingested, errors


# ---------------------------------------------------------------------------
# Task YAML bridge
# ---------------------------------------------------------------------------

def _find_task_yaml(repo_root: Path, task_id: str, task_path: str | None = None) -> Path | None:
    if task_path:
        candidate = repo_root / task_path
        if candidate.is_file():
            return candidate
    for state_dir in ("active", "blocked", "done"):
        path = repo_root / "tasks" / state_dir / f"{task_id}.yaml"
        if path.is_file():
            return path
    return None


def assignment_status_to_task_status(assignment_status: str) -> str | None:
    mapping = {
        "pending": TASK_STATUS_READY,
        "claimed": TASK_STATUS_ON_CLAIM,
        "building": TASK_STATUS_ON_CLAIM,
        "awaiting_review": TASK_STATUS_ON_COMPLETE,
        "accepted": "done",
        "changes_requested": TASK_STATUS_READY,
        "rejected": "blocked",
        "cancelled": "blocked",
    }
    return mapping.get(assignment_status)


def sync_task_status_from_assignment(
    repo_root: Path,
    *,
    task_id: str,
    assignment_status: str,
    task_path: str | None = None,
) -> list[str]:
    """Keep task YAML status aligned with assignment lifecycle (non-fatal)."""
    import yaml

    errors: list[str] = []
    target_status = assignment_status_to_task_status(assignment_status)
    if target_status is None:
        return errors
    path = _find_task_yaml(repo_root, task_id, task_path)
    if path is None:
        errors.append(f"task YAML for {task_id} not found; skipped status sync")
        return errors
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        errors.append(f"failed to read task YAML {path}: {exc}")
        return errors
    if not isinstance(data, dict):
        errors.append(f"task YAML {path} is not a mapping")
        return errors

    current = str(data.get("status", "")).strip().lower()
    if current == target_status:
        return errors

    data["status"] = target_status
    data["updated_at"] = utc_now()
    # Ensure reviewer exists when moving to review/done (protocol)
    if target_status in {"review", "done"} and not data.get("reviewer"):
        data["reviewer"] = "claude"

    state_dirs = {
        "ready": "active",
        "todo": "active",
        "in_progress": "active",
        "review": "active",
        "blocked": "blocked",
        "done": "done",
    }
    target_dir = state_dirs.get(target_status, "active")
    dest = repo_root / "tasks" / target_dir / path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        dest.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
            newline="\n",
        )
        if dest.resolve() != path.resolve() and path.exists():
            path.unlink()
    except OSError as exc:
        errors.append(f"failed to write task YAML: {exc}")
    return errors


def create_assignment_from_task_yaml(
    repo_root: Path,
    task_yaml_path: Path | str,
    *,
    base_branch: str | None = None,
    base_sha: str | None = None,
    new_branch: str | None = None,
    assigned_by: str = "claude",
    assigned_to: str = DEFAULT_ASSIGNED_TO,
    wake: bool = False,
) -> tuple[Path | None, list[str]]:
    """Create a full-contract assignment from tasks/active/*.yaml."""
    import yaml

    path = Path(task_yaml_path)
    if not path.is_absolute():
        path = (repo_root / path).resolve()
    try:
        task = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return None, [f"failed to load task YAML: {exc}"]
    if not isinstance(task, dict):
        return None, ["task YAML root must be a mapping"]

    task_id = str(task.get("id") or path.stem)
    title = str(task.get("title") or task_id)
    goals = task.get("goals") or []
    if isinstance(goals, list) and goals:
        goal = "; ".join(str(g) for g in goals)
    else:
        goal = str(task.get("objective") or task.get("context") or title)
    acceptance = task.get("acceptance") or task.get("acceptance_criteria") or []
    if not isinstance(acceptance, list):
        acceptance = [str(acceptance)]
    outputs = task.get("outputs") or []
    allowed = [str(o) for o in outputs] if isinstance(outputs, list) else []
    constraints = task.get("constraints") or []
    forbidden = list(DEFAULT_FORBIDDEN_OPERATIONS)
    if isinstance(constraints, list):
        for c in constraints:
            text = str(c).lower()
            if "merge" in text:
                forbidden.append("git_merge")
            if "push" in text:
                forbidden.append("git_push")

    try:
        rel_task = str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except ValueError:
        rel_task = str(path)
    return write_assignment(
        repo_root,
        task_id=task_id,
        title=title,
        goal=goal,
        base_branch=base_branch or "main",
        base_sha=base_sha,
        new_branch=new_branch or "",
        allowed_paths=allowed,
        forbidden_operations=sorted(set(forbidden)),
        acceptance_criteria=[str(a) for a in acceptance],
        verification_commands=[
            "python scripts/validate.py",
            "python scripts/run_tests.py",
        ],
        timeout=DEFAULT_TIMEOUT_SECONDS,
        handoff_path=None,
        assigned_by=assigned_by,
        assigned_to=assigned_to,
        task_path=rel_task,
        instructions=str(task.get("notes") or "") or None,
        wake=wake,
        required_mcp_servers=extract_required_mcp_servers(task),
    )


def format_assignment_contract(record: AssignmentRecord) -> str:
    """Human-readable full task contract for builder pickup."""
    lines = [
        f"# Assignment {record.assignment_id}",
        f"status: {record.status}",
        f"task_id: {record.task_id}",
        f"title: {record.title}",
        f"goal: {record.goal}",
        f"base_branch: {record.base_branch}",
        f"base_sha: {record.base_sha or '(none)'}",
        f"new_branch: {record.new_branch}",
        f"handoff_path: {record.handoff_path}",
        f"assigned_by: {record.assigned_by}",
        f"assigned_to: {record.assigned_to}",
        f"created_at: {record.created_at}",
        f"timeout: {record.timeout}s",
        f"adapter_id: {record.adapter_id}",
        f"execution_route: {record.execution_route}",
        f"task_path: {record.task_path or '(none)'}",
        "",
        "allowed_paths:",
    ]
    for p in record.allowed_paths or ["(none)"]:
        lines.append(f"  - {p}")
    lines.append("forbidden_operations:")
    for op in record.forbidden_operations or ["(none)"]:
        lines.append(f"  - {op}")
    lines.append("acceptance_criteria:")
    for c in record.acceptance_criteria or ["(none)"]:
        lines.append(f"  - {c}")
    lines.append("verification_commands:")
    for cmd in record.verification_commands or ["(none)"]:
        lines.append(f"  - {cmd}")
    if record.instructions:
        lines.extend(["", "instructions:", record.instructions])
    if record.correction_note:
        lines.extend(["", "correction_note:", record.correction_note])
    if record.resolution_note:
        lines.extend(
            [
                "",
                f"resolution_note (reviewed_by={record.reviewed_by or '-'} "
                f"at {record.reviewed_at or '-'}):",
                record.resolution_note,
            ]
        )
    if record.parse_errors:
        lines.extend(["", "schema_warnings:"])
        for err in record.parse_errors:
            lines.append(f"  - {err}")
    return "\n".join(lines) + "\n"
