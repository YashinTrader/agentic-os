from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


class RollbackDocTests(unittest.TestCase):
    def test_rollback_plan_exists(self) -> None:
        path = REPO_ROOT / "docs" / "PHASE_3_6_CODEX_ROLLBACK.md"
        self.assertTrue(path.exists(), "rollback plan required")
        text = path.read_text(encoding="utf-8")
        self.assertIn("emergency", text.lower())
        self.assertIn("supports_execution", text)

    def test_activation_readiness_doc_exists(self) -> None:
        path = REPO_ROOT / "docs" / "PHASE_3_6_CODEX_ACTIVATION_READINESS.md"
        self.assertTrue(path.exists())

    def test_human_approval_checklist_exists(self) -> None:
        path = REPO_ROOT / "docs" / "PHASE_3_6_HUMAN_APPROVAL_CHECKLIST.md"
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertIn("codex-restricted", text)
        self.assertNotIn("APPROVED BY GABRIEL", text.upper())


if __name__ == "__main__":
    unittest.main()