"""Phase 3.1 approval record contract — validation only. No auth, signing, or execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

APPROVER_TYPES = frozenset({"human", "reviewer", "system"})
APPROVAL_LEVELS = frozenset({"none", "reviewer", "human", "blocked"})


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
class ApprovalValidationResult:
    valid: bool
    fresh: bool
    blocked_reasons: list[str]


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


def validate_approval_record(record: ApprovalRecord | dict[str, Any]) -> ApprovalValidationResult:
    """Validate approval record shape and policy invariants."""
    blocked: list[str] = []

    if isinstance(record, ApprovalRecord):
        data = approval_record_to_dict(record)
    else:
        data = dict(record)

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
        if not data.get(key) and data.get(key) != False:
            blocked.append(f"missing approval field: {key}")

    level = str(data.get("approval_level", ""))
    if level not in APPROVAL_LEVELS:
        blocked.append(f"invalid approval_level: {level!r}")

    approver_type = str(data.get("approver_type", ""))
    if approver_type not in APPROVER_TYPES:
        blocked.append(f"invalid approver_type: {approver_type!r}")

    if data.get("revoked"):
        blocked.append("approval record is revoked")

    if level == "human" and approver_type == "system":
        blocked.append("system cannot approve high-risk (human-level) execution")

    if level in {"human", "reviewer"}:
        if not data.get("expires_at"):
            blocked.append("expires_at required for human/reviewer approvals")
        else:
            expires = _parse_iso8601(str(data["expires_at"]))
            if expires is None:
                blocked.append("expires_at is not valid ISO-8601")
            else:
                now = datetime.now(timezone.utc)
                if expires <= now:
                    blocked.append("approval has expired")

    if level == "none":
        blocked.append("approval_level none does not require an approval record for execution")

    preview_hash = str(data.get("preview_hash", ""))
    if not preview_hash or len(preview_hash) < 8:
        blocked.append("preview_hash must be a non-trivial digest")

    fresh = "expired" not in " ".join(blocked).lower() and "revoked" not in blocked

    return ApprovalValidationResult(
        valid=len(blocked) == 0 or (len(blocked) == 1 and "none does not require" in blocked[0]),
        fresh=fresh and not data.get("revoked", False),
        blocked_reasons=blocked,
    )


def approval_satisfies_level(record: ApprovalRecord, required_level: str) -> bool:
    """Check whether approver type can satisfy the required approval level."""
    if required_level == "none":
        return True
    if required_level == "blocked":
        return False
    if required_level == "reviewer":
        return record.approver_type in {"human", "reviewer"} and not record.revoked
    if required_level == "human":
        return record.approver_type == "human" and not record.revoked
    return False