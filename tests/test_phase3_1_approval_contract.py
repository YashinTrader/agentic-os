from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.approval_contract import (  # noqa: E402
    ApprovalRecord,
    DEFAULT_HUMAN_APPROVAL_TTL_MINUTES,
    DEFAULT_REVIEWER_APPROVAL_TTL_MINUTES,
    evaluate_approval_satisfaction,
    validate_approval_record_shape,
)


def _future_iso(minutes: int = 60) -> str:
    dt = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _past_iso(minutes: int = 60) -> str:
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sample_record(**overrides) -> ApprovalRecord:
    defaults = dict(
        approval_id="apr-001",
        task_id="T-PHASE3-1-DESIGN",
        run_id="dispatch-20260611T120000Z-abc12345",
        preview_hash="a" * 64,
        adapter_id="composer-cli-preview",
        approval_level="reviewer",
        approved_by="claude",
        approver_type="reviewer",
        approved_at="2026-06-11T12:00:00Z",
        expires_at=_future_iso(),
        scope="dispatch execution preview",
        allowed_command_hash="b" * 64,
        allowed_cwd=str(REPO_ROOT),
        allowed_scope_paths=("tasks/",),
        notes="",
        revoked=False,
    )
    defaults.update(overrides)
    return ApprovalRecord(**defaults)


class ApprovalContractTests(unittest.TestCase):
    def test_module_has_no_subprocess(self) -> None:
        source = (REPO_ROOT / "dispatch" / "approval_contract.py").read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("subprocess.", source)

    def test_shape_valid_reviewer_record(self) -> None:
        result = validate_approval_record_shape(_sample_record())
        self.assertTrue(result.well_formed)
        self.assertEqual(result.reasons, [])

    def test_approval_level_none_requires_no_record(self) -> None:
        result = evaluate_approval_satisfaction(None, "hash", "none")
        self.assertTrue(result.satisfied)
        self.assertEqual(result.status, "none")
        self.assertEqual(result.reasons, [])

    def test_blocked_approval_cannot_be_satisfied(self) -> None:
        result = evaluate_approval_satisfaction(_sample_record(), "a" * 64, "blocked")
        self.assertFalse(result.satisfied)
        self.assertEqual(result.status, "blocked")

    def test_reviewer_can_satisfy_reviewer(self) -> None:
        record = _sample_record(approver_type="reviewer", approval_level="reviewer")
        result = evaluate_approval_satisfaction(record, record.preview_hash, "reviewer")
        self.assertTrue(result.satisfied)
        self.assertEqual(result.status, "approved")

    def test_human_can_satisfy_reviewer(self) -> None:
        record = _sample_record(approver_type="human", approval_level="human")
        result = evaluate_approval_satisfaction(record, record.preview_hash, "reviewer")
        self.assertTrue(result.satisfied)
        self.assertEqual(result.status, "approved")

    def test_reviewer_cannot_satisfy_human(self) -> None:
        record = _sample_record(approver_type="reviewer", approval_level="reviewer")
        result = evaluate_approval_satisfaction(record, record.preview_hash, "human")
        self.assertFalse(result.satisfied)
        self.assertEqual(result.status, "pending")
        self.assertTrue(any("human approval required" in r for r in result.reasons))

    def test_expired_record_rejected(self) -> None:
        record = _sample_record(expires_at=_past_iso())
        shape = validate_approval_record_shape(record)
        self.assertTrue(shape.well_formed)
        result = evaluate_approval_satisfaction(record, record.preview_hash, "reviewer")
        self.assertFalse(result.satisfied)
        self.assertEqual(result.status, "expired")

    def test_revoked_record_rejected(self) -> None:
        record = _sample_record(revoked=True)
        result = evaluate_approval_satisfaction(record, record.preview_hash, "reviewer")
        self.assertFalse(result.satisfied)
        self.assertEqual(result.status, "revoked")
        self.assertEqual(result.reasons, ["approval record is revoked"])

    def test_preview_hash_mismatch_marked_stale(self) -> None:
        record = _sample_record()
        result = evaluate_approval_satisfaction(record, "b" * 64, "reviewer")
        self.assertFalse(result.satisfied)
        self.assertEqual(result.status, "stale")

    def test_malformed_record_marked_invalid(self) -> None:
        result = evaluate_approval_satisfaction({"approval_id": ""}, "a" * 64, "reviewer")
        self.assertFalse(result.satisfied)
        self.assertEqual(result.status, "invalid")
        self.assertTrue(any(r.startswith("missing:") or r.startswith("invalid:") for r in result.reasons))

    def test_system_cannot_sign_human_level_shape(self) -> None:
        result = validate_approval_record_shape(
            _sample_record(approval_level="human", approver_type="system")
        )
        self.assertFalse(result.well_formed)
        self.assertTrue(any("system cannot sign" in r for r in result.reasons))

    def test_default_ttl_constants_documented(self) -> None:
        self.assertEqual(DEFAULT_HUMAN_APPROVAL_TTL_MINUTES, 30)
        self.assertEqual(DEFAULT_REVIEWER_APPROVAL_TTL_MINUTES, 60)


if __name__ == "__main__":
    unittest.main()