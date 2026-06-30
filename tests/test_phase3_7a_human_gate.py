from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_activation import (  # noqa: E402
    build_human_approval_request,
    validate_human_approval_request,
)


class Phase37aHumanGateTests(unittest.TestCase):
    REVIEWED = "d9f203c39c3a85613ef4c7f76e110e3f4734d9c1"

    def test_request_package_valid(self) -> None:
        request = build_human_approval_request(
            REPO_ROOT,
            activation_id="activation-human-test",
            reviewed_commit_sha=self.REVIEWED,
            cli_version="0.136.0",
        )
        blockers = validate_human_approval_request(request)
        self.assertEqual(blockers, [])
        self.assertEqual(request["status"], "awaiting_human_decision")
        self.assertIn("does not itself authorize", request["statement"])

    def test_request_rejects_approval_fields(self) -> None:
        request = build_human_approval_request(
            REPO_ROOT,
            activation_id="activation-human-test",
            reviewed_commit_sha=self.REVIEWED,
        )
        request["signature"] = "fake"
        blockers = validate_human_approval_request(request)
        self.assertTrue(any("forbidden" in b for b in blockers))

    def test_request_not_approved(self) -> None:
        request = build_human_approval_request(
            REPO_ROOT,
            activation_id="activation-human-test",
            reviewed_commit_sha=self.REVIEWED,
        )
        request["approved"] = True
        blockers = validate_human_approval_request(request)
        self.assertTrue(blockers)


if __name__ == "__main__":
    unittest.main()