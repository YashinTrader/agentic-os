from __future__ import annotations

import unittest

from orchestrator.risk import evaluate_risk


class RiskGateTests(unittest.TestCase):
    def test_human_required_for_deploy(self) -> None:
        task = {"title": "Deploy to production", "objective": "Update CI/CD pipeline", "risk_level": "high"}
        result = evaluate_risk(task, {})
        self.assertTrue(result["approval_required"])
        self.assertEqual(result["approval_level"], "human")

    def test_human_required_for_secrets(self) -> None:
        task = {"title": "Add API key handling", "objective": "Store secrets in vault"}
        result = evaluate_risk(task, {})
        self.assertEqual(result["approval_level"], "human")

    def test_no_human_for_read_only_planning(self) -> None:
        task = {
            "title": "Dry-run sync planning",
            "objective": "Read-only planning for Obsidian dry-run sync summary",
            "risk_level": "low",
        }
        result = evaluate_risk(task, {})
        self.assertFalse(result["approval_required"])
        self.assertEqual(result["approval_level"], "none")

    def test_reviewer_for_registry_change(self) -> None:
        task = {"title": "Add registry entry", "objective": "Extend teams registry schema"}
        result = evaluate_risk(task, {})
        self.assertEqual(result["approval_level"], "reviewer")


if __name__ == "__main__":
    unittest.main()