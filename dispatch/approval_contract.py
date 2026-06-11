"""Phase 3.1 approval record contract — validation only. No auth, signing, or execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

APPROVER_TYPES = frozenset({"human", "reviewer", "system"})
APPROVAL_LEVELS = frozenset({"none", "reviewer", "human", "blocked"})

# Default TTLs (ADR-0015 / Phase 3.1 cleanup decisions)
DEFAULT_HUMAN_APPROVAL_TTL_MINUTES = 30
DEFAULT_REVIEWER_APPROVAL_TTL_MINUTES = 60

ApprovalSatisfactionStatus = Literal[
    "none",
    "pending",
    "approved",
    "blocked",
    "stale",
    "expired",
    "revoked",
    "invalid",
]


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    task_id: str
    run_id: str
    preview_hash: str
    adapter_id: str
    approval_level: str
    approved_by: str
    approver_type: str
    approved_at: str
    expires_at: str
    scope: str
    allowed_command_hash: str
    allowed_cwd: str
    allowed_scope_paths: tuple[str, ...]
    notes: str = ""
    revoked: bool = False


@dataclass
class ApprovalShapeResult:
    """Well-formed approval record — schema/required fields only."""

    well_formed: bool
    reasons: list[str]


@dataclass
class ApprovalSatisfactionResult:
    """Whether approval satisfies execution requirements."""

    satisfied: bool
    status: ApprovalSatisfactionStatus
    reasons: list[str]


def _parse_iso8601(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def approval_record_to_dict(record: ApprovalRecord) -> dict[str, Any]:
    data = asdict(record)
    data["allowed_scope_paths"] = list(record.allowed_scope_paths)
    return data


def _normalize_record(record: ApprovalRecord | dict[str, Any]) -> dict[str, Any]:
    if isinstance(record, ApprovalRecord):
        return approval_record_to_dict(record)
    return dict(record)


def default_approval_expires_at(
    approval_level: str,
    *,
    approved_at: datetime | None = None,
) -> str:
    """Compute default expiry ISO-8601 Z for human/reviewer approvals."""
    base = approved_at or datetime.now(timezone.utc)
    if approval_level == "human":
        delta = timedelta(minutes=DEFAULT_HUMAN_APPROVAL_TTL_MINUTES)
    elif approval_level == "reviewer":
        delta = timedelta(minutes=DEFAULT_REVIEWER_APPROVAL_TTL_MINUTES)
    else:
        delta = timedelta(minutes=0)
    expires = base + delta
    return expires.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_approval_record_shape(record: ApprovalRecord | dict[str, Any]) -> ApprovalShapeResult:
    """Check schema/required fields/types. Does not decide execution approval."""
    reasons: list[str] = []
    data = _normalize_record(record)

    required = (
        "approval_id",
        "task_id",
        "run_id",
        "preview_hash",
        "adapter_id",
        "approval_level",
        "approved_by",
        "approver_type",
        "approved_at",
        "expires_at",
        "scope",
        "allowed_command_hash",
        "allowed_cwd",
        "allowed_scope_paths",
    )
    for key in required:
        if not data.get(key) and data.get(key) is not False:
            reasons.append(f"missing: {key}")

    level = str(data.get("approval_level", ""))
    if level not in APPROVAL_LEVELS:
        reasons.append(f"invalid: approval_level ({level!r})")

    approver_type = str(data.get("approver_type", ""))
    if approver_type not in APPROVER_TYPES:
        reasons.append(f"invalid: approver_type ({approver_type!r})")

    preview_hash = str(data.get("preview_hash", ""))
    if not preview_hash or len(preview_hash) < 8:
        reasons.append("invalid: preview_hash (must be non-trivial digest)")

    if level in {"human", "reviewer"}:
        if not data.get("expires_at"):
            reasons.append("missing: expires_at")
        else:
            expires = _parse_iso8601(str(data["expires_at"]))
            if expires is None:
                reasons.append("invalid: expires_at (not valid ISO-8601)")

    if level == "human" and approver_type == "system":
        reasons.append("invalid: approver_type (system cannot sign human-level records)")

    return ApprovalShapeResult(well_formed=len(reasons) == 0, reasons=reasons)


def evaluate_approval_satisfaction(
    record: ApprovalRecord | dict[str, Any] | None,
    preview_hash: str,
    required_approval_level: str,
    *,
    now: datetime | None = None,
) -> ApprovalSatisfactionResult:
    """Check whether approval satisfies the required level for execution."""
    if required_approval_level == "none":
        return ApprovalSatisfactionResult(satisfied=True, status="none", reasons=[])

    if required_approval_level == "blocked":
        return ApprovalSatisfactionResult(
            satisfied=False,
            status="blocked",
            reasons=["required approval level is blocked"],
        )

    if required_approval_level not in APPROVAL_LEVELS:
        return ApprovalSatisfactionResult(
            satisfied=False,
            status="invalid",
            reasons=[f"invalid: required_approval_level ({required_approval_level!r})"],
        )

    if record is None:
        return ApprovalSatisfactionResult(
            satisfied=False,
            status="pending",
            reasons=["approval record required but not provided"],
        )

    shape = validate_approval_record_shape(record)
    if not shape.well_formed:
        return ApprovalSatisfactionResult(
            satisfied=False,
            status="invalid",
            reasons=list(shape.reasons),
        )

    data = _normalize_record(record)
    reasons: list[str] = []

    if data.get("revoked"):
        return ApprovalSatisfactionResult(
            satisfied=False,
            status="revoked",
            reasons=["approval record is revoked"],
        )

    record_hash = str(data.get("preview_hash", ""))
    if record_hash != preview_hash:
        return ApprovalSatisfactionResult(
            satisfied=False,
            status="stale",
            reasons=["preview_hash mismatch — approval is stale"],
        )

    expires = _parse_iso8601(str(data.get("expires_at", "")))
    current = now or datetime.now(timezone.utc)
    if expires is None or expires <= current:
        return ApprovalSatisfactionResult(
            satisfied=False,
            status="expired",
            reasons=["approval has expired"],
        )

    approver_type = str(data.get("approver_type", ""))

    if required_approval_level == "human":
        if approver_type != "human":
            reasons.append("human approval required; record approver_type is not human")
            return ApprovalSatisfactionResult(
                satisfied=False,
                status="pending",
                reasons=reasons,
            )

    if required_approval_level == "reviewer":
        if approver_type not in {"human", "reviewer"}:
            reasons.append("reviewer or human approval required")
            return ApprovalSatisfactionResult(
                satisfied=False,
                status="pending",
                reasons=reasons,
            )

    return ApprovalSatisfactionResult(satisfied=True, status="approved", reasons=[])


def approval_satisfies_level(record: ApprovalRecord, required_level: str) -> bool:
    """Legacy helper — prefer evaluate_approval_satisfaction."""
    result = evaluate_approval_satisfaction(
        record,
        record.preview_hash,
        required_level,
    )
    return result.satisfied