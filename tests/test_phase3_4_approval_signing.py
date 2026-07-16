from __future__ import annotations

import hashlib
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.approval_contract import (  # noqa: E402
    DEFAULT_HUMAN_APPROVAL_TTL_MINUTES,
    DEFAULT_REVIEWER_APPROVAL_TTL_MINUTES,
)
from dispatch.approval_signing import (  # noqa: E402
    APPROVER_ENV_KEYS,
    build_unsigned_signed_record,
    sign_approval_record,
    validate_ttl_minutes,
    verify_signed_approval,
)
from dispatch.freshness import compute_preview_hash  # noqa: E402


class ApprovalSigningTests(unittest.TestCase):
    REVIEWER_KEY = "reviewer-test-secret-key"
    HUMAN_KEY = "human-test-secret-key"

    def setUp(self) -> None:
        os.environ["AGENTIC_OS_REVIEWER_APPROVAL_KEY"] = self.REVIEWER_KEY
        os.environ["AGENTIC_OS_HUMAN_APPROVAL_KEY"] = self.HUMAN_KEY
        os.environ["AGENTIC_OS_REVIEWER_APPROVAL_KEY_ID"] = "reviewer-test"
        os.environ["AGENTIC_OS_HUMAN_APPROVAL_KEY_ID"] = "human-test"

    def tearDown(self) -> None:
        for name in (
            "AGENTIC_OS_REVIEWER_APPROVAL_KEY",
            "AGENTIC_OS_HUMAN_APPROVAL_KEY",
            "AGENTIC_OS_REVIEWER_APPROVAL_KEY_ID",
            "AGENTIC_OS_HUMAN_APPROVAL_KEY_ID",
        ):
            os.environ.pop(name, None)

    def _unsigned(
        self,
        *,
        approver_type: str = "reviewer",
        ttl_minutes: int | None = None,
        command: str = 'python -c "print(1)"',
        cwd: str = "/repo",
    ) -> dict:
        cmd_hash = hashlib.sha256(command.encode("utf-8")).hexdigest()
        return build_unsigned_signed_record(
            approval_id="approval-test-001",
            task_id="T-SIGN",
            run_id="run-sign-001",
            preview_id="preview-sign-001",
            preview_hash="a" * 64,
            adapter_id="local-python-exec-test",
            approval_level="reviewer",
            approver_type=approver_type,
            approved_by="test-reviewer",
            allowed_command_hash=cmd_hash,
            allowed_cwd=cwd,
            allowed_scope_paths=["tasks/"],
            ttl_minutes=ttl_minutes,
            nonce="fixed-nonce-001",
        )

    def test_hmac_sign_and_verify_round_trip(self) -> None:
        preview = {
            "task_id": "T-SIGN",
            "run_id": "run-sign-001",
            "adapter_id": "local-python-exec-test",
            "command": 'python -c "print(1)"',
            "working_directory": "/repo",
            "scope_paths": ["tasks/"],
        }
        preview_hash = compute_preview_hash(preview)
        unsigned = self._unsigned()
        unsigned["preview_hash"] = preview_hash
        signed = sign_approval_record(unsigned, approver_type="reviewer")
        self.assertTrue(signed.success, signed.errors)
        assert signed.record is not None

        without_preview = verify_signed_approval(signed.record)
        self.assertEqual(without_preview.status, "valid")
        self.assertEqual(without_preview.errors, [])

        with_preview = verify_signed_approval(signed.record, preview=preview)
        self.assertEqual(with_preview.status, "valid")

    def test_key_separation_reviewer_vs_human(self) -> None:
        reviewer_unsigned = self._unsigned(approver_type="reviewer")
        reviewer_signed = sign_approval_record(reviewer_unsigned, approver_type="reviewer")
        self.assertTrue(reviewer_signed.success, reviewer_signed.errors)
        assert reviewer_signed.record is not None

        os.environ.pop("AGENTIC_OS_REVIEWER_APPROVAL_KEY", None)
        missing_reviewer = verify_signed_approval(reviewer_signed.record)
        self.assertEqual(missing_reviewer.status, "wrong_key")

        os.environ["AGENTIC_OS_REVIEWER_APPROVAL_KEY"] = "wrong-reviewer-key"
        os.environ["AGENTIC_OS_HUMAN_APPROVAL_KEY"] = self.HUMAN_KEY
        wrong_reviewer_secret = verify_signed_approval(reviewer_signed.record)
        self.assertEqual(wrong_reviewer_secret.status, "invalid")

        human_unsigned = self._unsigned(approver_type="human")
        human_signed = sign_approval_record(human_unsigned, approver_type="human")
        self.assertTrue(human_signed.success, human_signed.errors)
        assert human_signed.record is not None

        os.environ.pop("AGENTIC_OS_HUMAN_APPROVAL_KEY", None)
        os.environ["AGENTIC_OS_REVIEWER_APPROVAL_KEY"] = self.REVIEWER_KEY
        human_with_reviewer_key = verify_signed_approval(human_signed.record)
        self.assertEqual(human_with_reviewer_key.status, "wrong_key")

    def test_ttl_max_enforced(self) -> None:
        over_reviewer = validate_ttl_minutes(
            "reviewer",
            DEFAULT_REVIEWER_APPROVAL_TTL_MINUTES + 1,
        )
        self.assertTrue(over_reviewer)

        over_human = validate_ttl_minutes(
            "human",
            DEFAULT_HUMAN_APPROVAL_TTL_MINUTES + 1,
        )
        self.assertTrue(over_human)

        unsigned = self._unsigned(ttl_minutes=DEFAULT_REVIEWER_APPROVAL_TTL_MINUTES + 5)
        unsigned["expires_at"] = (
            datetime.now(timezone.utc) + timedelta(minutes=DEFAULT_REVIEWER_APPROVAL_TTL_MINUTES + 5)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        signed = sign_approval_record(unsigned, approver_type="reviewer")
        self.assertTrue(signed.success, signed.errors)
        assert signed.record is not None

        future = datetime.now(timezone.utc) + timedelta(minutes=DEFAULT_REVIEWER_APPROVAL_TTL_MINUTES + 10)
        expired = verify_signed_approval(signed.record, now=future)
        self.assertEqual(expired.status, "expired")

    def test_changed_field_invalidates_signature(self) -> None:
        unsigned = self._unsigned()
        signed = sign_approval_record(unsigned, approver_type="reviewer")
        self.assertTrue(signed.success, signed.errors)
        assert signed.record is not None

        tampered = dict(signed.record)
        tampered["preview_hash"] = "b" * 64
        invalid = verify_signed_approval(tampered)
        self.assertEqual(invalid.status, "invalid")

        preview = {
            "task_id": "T-SIGN",
            "run_id": "run-sign-001",
            "adapter_id": "local-python-exec-test",
            "command": 'python -c "print(1)"',
            "working_directory": "/repo",
            "scope_paths": ["tasks/"],
        }
        stale = verify_signed_approval(signed.record, preview=preview)
        self.assertEqual(stale.status, "stale")

    def test_no_secret_in_serialized_output(self) -> None:
        unsigned = self._unsigned(approver_type="human")
        signed = sign_approval_record(unsigned, approver_type="human")
        self.assertTrue(signed.success, signed.errors)
        assert signed.record is not None

        blob = json.dumps(signed.record, sort_keys=True)
        self.assertNotIn(self.REVIEWER_KEY, blob)
        self.assertNotIn(self.HUMAN_KEY, blob)
        for env_name in APPROVER_ENV_KEYS.values():
            self.assertNotIn(env_name, blob)


if __name__ == "__main__":
    unittest.main()