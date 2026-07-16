"""Phase 3.4 HMAC-SHA256 approval authenticity — local key possession, not legal identity."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from dispatch.approval_contract import (
    DEFAULT_HUMAN_APPROVAL_TTL_MINUTES,
    DEFAULT_REVIEWER_APPROVAL_TTL_MINUTES,
    _parse_iso8601,
)

SIGNING_VERSION = 2
SIGNING_ALGORITHM = "HMAC-SHA256"

APPROVER_ENV_KEYS = {
    "reviewer": "AGENTIC_OS_REVIEWER_APPROVAL_KEY",
    "human": "AGENTIC_OS_HUMAN_APPROVAL_KEY",
}

APPROVER_KEY_ID_ENV = {
    "reviewer": "AGENTIC_OS_REVIEWER_APPROVAL_KEY_ID",
    "human": "AGENTIC_OS_HUMAN_APPROVAL_KEY_ID",
}

DEFAULT_KEY_IDS = {"reviewer": "reviewer-v1", "human": "human-v1"}

MAX_TTL_MINUTES = {
    "human": DEFAULT_HUMAN_APPROVAL_TTL_MINUTES,
    "reviewer": DEFAULT_REVIEWER_APPROVAL_TTL_MINUTES,
}

VerificationStatus = Literal[
    "valid",
    "invalid",
    "expired",
    "revoked",
    "stale",
    "wrong_key",
    "wrong_scope",
    "replayed",
    "malformed",
]

SIGNED_REQUIRED_FIELDS = (
    "approval_id",
    "version",
    "task_id",
    "run_id",
    "preview_id",
    "preview_hash",
    "adapter_id",
    "approval_level",
    "approver_type",
    "approved_by",
    "issued_at",
    "expires_at",
    "nonce",
    "key_id",
    "algorithm",
    "allowed_command_hash",
    "allowed_cwd",
    "allowed_scope_paths",
    "worktree_allocation_id",
    "revoked",
)


@dataclass
class SigningResult:
    success: bool
    record: dict[str, Any] | None
    errors: list[str]


@dataclass
class VerificationResult:
    status: VerificationStatus
    errors: list[str]


def _normalize_path_for_signing(path: str) -> str:
    if not path:
        return ""
    return str(Path(path).as_posix())


def _normalize_scope_paths(paths: list[str] | tuple[str, ...]) -> list[str]:
    return [_normalize_path_for_signing(str(p)) for p in paths]


def canonical_signing_payload(record: dict[str, Any]) -> bytes:
    """Build canonical UTF-8 JSON bytes for HMAC (signature excluded)."""
    payload = {k: v for k, v in record.items() if k != "signature"}
    if "allowed_cwd" in payload:
        payload["allowed_cwd"] = _normalize_path_for_signing(str(payload["allowed_cwd"]))
    if "allowed_scope_paths" in payload:
        payload["allowed_scope_paths"] = _normalize_scope_paths(
            list(payload.get("allowed_scope_paths") or [])
        )
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _get_secret(approver_type: str) -> tuple[bytes | None, str]:
    env_name = APPROVER_ENV_KEYS.get(approver_type)
    if not env_name:
        return None, ""
    raw = os.environ.get(env_name, "")
    if not raw:
        return None, ""
    key_id_env = APPROVER_KEY_ID_ENV.get(approver_type, "")
    key_id = os.environ.get(key_id_env, DEFAULT_KEY_IDS.get(approver_type, ""))
    return raw.encode("utf-8"), key_id


def validate_ttl_minutes(approver_type: str, ttl_minutes: int | None) -> list[str]:
    if ttl_minutes is None:
        return []
    maximum = MAX_TTL_MINUTES.get(approver_type)
    if maximum is None:
        return [f"unknown approver_type for TTL: {approver_type!r}"]
    if ttl_minutes > maximum:
        return [f"TTL {ttl_minutes}m exceeds maximum {maximum}m for {approver_type}"]
    if ttl_minutes <= 0:
        return ["TTL must be positive"]
    return []


def compute_expires_at(approver_type: str, issued_at: datetime, ttl_minutes: int | None) -> str:
    if ttl_minutes is not None:
        delta = timedelta(minutes=ttl_minutes)
    elif approver_type == "human":
        delta = timedelta(minutes=DEFAULT_HUMAN_APPROVAL_TTL_MINUTES)
    elif approver_type == "reviewer":
        delta = timedelta(minutes=DEFAULT_REVIEWER_APPROVAL_TTL_MINUTES)
    else:
        delta = timedelta(minutes=0)
    expires = issued_at + delta
    return expires.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_unsigned_signed_record(
    *,
    approval_id: str,
    task_id: str,
    run_id: str,
    preview_id: str,
    preview_hash: str,
    adapter_id: str,
    approval_level: str,
    approver_type: str,
    approved_by: str,
    allowed_command_hash: str,
    allowed_cwd: str,
    allowed_scope_paths: list[str],
    worktree_allocation_id: str = "",
    notes: str = "",
    ttl_minutes: int | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    issued_dt = datetime.now(timezone.utc)
    issued_at = issued_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    _, key_id = _get_secret(approver_type)
    if not key_id:
        key_id = DEFAULT_KEY_IDS.get(approver_type, "unknown")

    return {
        "approval_id": approval_id,
        "version": SIGNING_VERSION,
        "task_id": task_id,
        "run_id": run_id,
        "preview_id": preview_id,
        "preview_hash": preview_hash,
        "adapter_id": adapter_id,
        "approval_level": approval_level,
        "approver_type": approver_type,
        "approved_by": approved_by,
        "issued_at": issued_at,
        "expires_at": compute_expires_at(approver_type, issued_dt, ttl_minutes),
        "nonce": nonce or os.urandom(16).hex(),
        "key_id": key_id,
        "algorithm": SIGNING_ALGORITHM,
        "allowed_command_hash": allowed_command_hash,
        "allowed_cwd": allowed_cwd,
        "allowed_scope_paths": list(allowed_scope_paths),
        "worktree_allocation_id": worktree_allocation_id,
        "notes": notes,
        "revoked": False,
        "signature": "",
    }


def sign_approval_record(record: dict[str, Any], *, approver_type: str) -> SigningResult:
    errors: list[str] = []
    data = dict(record)
    if str(data.get("approver_type", "")) != approver_type:
        errors.append("approver_type mismatch between record and signing request")
    if str(data.get("approval_level", "")) == "blocked":
        errors.append("cannot sign blocked approval level")

    secret, key_id = _get_secret(approver_type)
    if secret is None:
        errors.append(f"missing signing key for approver_type {approver_type!r}")

    for field in SIGNED_REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"missing required field: {field}")

    if data.get("algorithm") != SIGNING_ALGORITHM:
        errors.append(f"unsupported algorithm: {data.get('algorithm')!r}")

    expires = _parse_iso8601(str(data.get("expires_at", "")))
    if expires and expires <= datetime.now(timezone.utc):
        errors.append("approval record already expired")

    if errors:
        return SigningResult(False, None, errors)

    data["key_id"] = key_id or data.get("key_id", "")
    data["version"] = SIGNING_VERSION
    data["algorithm"] = SIGNING_ALGORITHM
    payload = canonical_signing_payload(data)
    digest = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    signed = dict(data)
    signed["signature"] = digest
    return SigningResult(True, signed, [])


def verify_signed_approval(
    record: dict[str, Any],
    *,
    preview: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> VerificationResult:
    errors: list[str] = []
    if not isinstance(record, dict):
        return VerificationResult("malformed", ["record must be a dict"])

    for field in SIGNED_REQUIRED_FIELDS:
        if field not in record:
            errors.append(f"missing: {field}")
    signature = str(record.get("signature", ""))
    if not signature or not re.fullmatch(r"[0-9a-f]{64}", signature):
        errors.append("missing or invalid signature")
    if errors:
        return VerificationResult("malformed", errors)

    approver_type = str(record.get("approver_type", ""))
    secret, expected_key_id = _get_secret(approver_type)
    if secret is None:
        return VerificationResult("wrong_key", ["signing key not available for verification"])

    record_key_id = str(record.get("key_id", ""))
    if expected_key_id and record_key_id != expected_key_id:
        return VerificationResult("wrong_key", ["key_id does not match configured key"])

    payload = canonical_signing_payload(record)
    expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return VerificationResult("invalid", ["signature mismatch"])

    if record.get("revoked"):
        return VerificationResult("revoked", ["approval is revoked"])

    current = now or datetime.now(timezone.utc)
    expires = _parse_iso8601(str(record.get("expires_at", "")))
    if expires is None or expires <= current:
        return VerificationResult("expired", ["approval has expired"])

    if preview is not None:
        from dispatch.freshness import compute_preview_hash

        preview_hash = compute_preview_hash(preview)
        if str(record.get("preview_hash", "")) != preview_hash:
            return VerificationResult("stale", ["preview_hash mismatch"])

        if str(record.get("task_id", "")) != str(preview.get("task_id", "")):
            return VerificationResult("wrong_scope", ["task_id mismatch"])
        if str(record.get("run_id", "")) != str(preview.get("run_id", "")):
            return VerificationResult("wrong_scope", ["run_id mismatch"])
        if str(record.get("adapter_id", "")) != str(preview.get("adapter_id", "")):
            return VerificationResult("wrong_scope", ["adapter_id mismatch"])

        command = str(preview.get("command", ""))
        cmd_hash = hashlib.sha256(command.encode("utf-8")).hexdigest()
        if str(record.get("allowed_command_hash", "")) != cmd_hash:
            return VerificationResult("wrong_scope", ["command hash mismatch"])

        cwd = str(preview.get("working_directory", ""))
        if _normalize_path_for_signing(str(record.get("allowed_cwd", ""))) != _normalize_path_for_signing(cwd):
            return VerificationResult("wrong_scope", ["cwd mismatch"])

        scope = _normalize_scope_paths(list(preview.get("scope_paths") or []))
        record_scope = _normalize_scope_paths(list(record.get("allowed_scope_paths") or []))
        if scope != record_scope:
            return VerificationResult("wrong_scope", ["scope_paths mismatch"])

    return VerificationResult("valid", [])


def upgrade_legacy_to_signable(legacy: dict[str, Any], *, preview_id: str = "") -> dict[str, Any]:
    """Map Phase 3.2 approval record fields to signed v2 shape (unsigned)."""
    return build_unsigned_signed_record(
        approval_id=str(legacy.get("approval_id", "")),
        task_id=str(legacy.get("task_id", "")),
        run_id=str(legacy.get("run_id", "")),
        preview_id=preview_id or str(legacy.get("preview_id", legacy.get("run_id", ""))),
        preview_hash=str(legacy.get("preview_hash", "")),
        adapter_id=str(legacy.get("adapter_id", "")),
        approval_level=str(legacy.get("approval_level", "")),
        approver_type=str(legacy.get("approver_type", "")),
        approved_by=str(legacy.get("approved_by", "")),
        allowed_command_hash=str(legacy.get("allowed_command_hash", "")),
        allowed_cwd=str(legacy.get("allowed_cwd", "")),
        allowed_scope_paths=list(legacy.get("allowed_scope_paths") or []),
        worktree_allocation_id=str(legacy.get("worktree_allocation_id", "")),
        notes=str(legacy.get("notes", "")),
    )