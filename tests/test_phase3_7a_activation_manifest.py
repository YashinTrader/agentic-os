from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_activation import (  # noqa: E402
    build_activation_manifest_v2,
    validate_activation_manifest_v2,
)


class Phase37aActivationManifestTests(unittest.TestCase):
    REVIEWED = "d9f203c39c3a85613ef4c7f76e110e3f4734d9c1"

    def test_manifest_permitted_status(self) -> None:
        manifest = build_activation_manifest_v2(
            REPO_ROOT,
            activation_id="activation-phase37a-test",
            reviewed_commit_sha=self.REVIEWED,
            cli_version="0.136.0",
            cli_help_hash="fixture-hash",
            status="awaiting_claude_review",
        )
        result = validate_activation_manifest_v2(
            manifest, repo_root=REPO_ROOT, current_reviewed_sha=self.REVIEWED, phase="3.7A"
        )
        self.assertTrue(result.ready_for_review, result.blockers)

    def test_forbidden_statuses_blocked(self) -> None:
        for status in ("human_approved", "activation_ready", "active", "completed"):
            manifest = build_activation_manifest_v2(
                REPO_ROOT,
                activation_id="activation-forbidden",
                reviewed_commit_sha=self.REVIEWED,
                cli_version="0.136.0",
                cli_help_hash="fixture-hash",
                status=status,
            )
            result = validate_activation_manifest_v2(manifest, repo_root=REPO_ROOT, phase="3.7A")
            self.assertFalse(result.ready_for_review)
            self.assertTrue(any("forbidden" in b for b in result.blockers))

    def test_fabricated_approval_reference_blocked(self) -> None:
        manifest = build_activation_manifest_v2(
            REPO_ROOT,
            activation_id="activation-fabricated",
            reviewed_commit_sha=self.REVIEWED,
            cli_version="0.136.0",
            cli_help_hash="fixture-hash",
        )
        manifest["human_approval_reference"] = "fake-approval"
        result = validate_activation_manifest_v2(manifest, repo_root=REPO_ROOT, phase="3.7A")
        self.assertFalse(result.ready_for_review)
        self.assertTrue(any("fabricated" in b for b in result.blockers))

    def test_live_run_authorized_must_be_false(self) -> None:
        manifest = build_activation_manifest_v2(
            REPO_ROOT,
            activation_id="activation-live",
            reviewed_commit_sha=self.REVIEWED,
            cli_version="0.136.0",
            cli_help_hash="fixture-hash",
        )
        manifest["live_run_authorized"] = True
        result = validate_activation_manifest_v2(manifest, repo_root=REPO_ROOT, phase="3.7A")
        self.assertFalse(result.ready_for_review)


if __name__ == "__main__":
    unittest.main()