from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.approval_contract import ApprovalRecord, validate_approval_record  # noqa: E402


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

    def test_valid_reviewer_approval(self) -> None:
        result = validate_approval_record(_sample_record())
        self.assertTrue(result.fresh)
        self.assertFalse(any("expired" in r for r in result.blocked_reasons))

    def test_expired_approval_invalid(self) -> None:
        result = validate_approval_record(_sample_record(expires_at=_past_iso()))
        self.assertFalse(result.fresh)
        self.assertTrue(any("expired" in r for r in result.blocked_reasons))

    def test_system_cannot_approve_human_level(self) -> None:
        result = validate_approval_record(
            _sample_record(approval_level="human", approver_type="system")
        )
        self.assertTrue(any("system cannot approve" in r for r in result.blocked_reasons))

    def test_revoked_approval_invalid(self) -> None:
        result = validate_approval_record(_sample_record(revoked=True))
        self.assertFalse(result.fresh)
        self.assertTrue(any("revoked" in r for r in result.blocked_reasons))


if __name__ == "__main__":
    unittest.main()