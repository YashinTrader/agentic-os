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

    def test_dry_run_plus_production_deploy_is_human(self) -> None:
        task = {
            "title": "Orchestration dry-run",
            "objective": "Dry-run plan for production deploy",
            "risk_level": "low",
        }
        result = evaluate_risk(task, {})
        self.assertEqual(result["approval_level"], "human")
        self.assertTrue(result["approval_required"])

    def test_read_only_plus_secrets_is_human(self) -> None:
        task = {
            "title": "Security review",
            "objective": "Read-only review of secrets handling",
            "risk_level": "low",
        }
        result = evaluate_risk(task, {})
        self.assertEqual(result["approval_level"], "human")

    def test_requires_human_approval_flag_without_keywords(self) -> None:
        task = {
            "title": "Benign task",
            "objective": "Add unit tests for helper module",
            "requires_human_approval": True,
            "risk_level": "low",
        }
        result = evaluate_risk(task, {})
        self.assertEqual(result["approval_level"], "human")

    def test_high_risk_level_without_keywords(self) -> None:
        task = {
            "title": "Benign task",
            "objective": "Add unit tests for helper module",
            "risk_level": "high",
        }
        result = evaluate_risk(task, {})
        self.assertEqual(result["approval_level"], "human")

    def test_ci_deployment_plan_is_human(self) -> None:
        task = {"title": "Release prep", "objective": "Plan CI deployment steps", "risk_level": "medium"}
        result = evaluate_risk(task, {})
        self.assertEqual(result["approval_level"], "human")

    def test_delete_files_is_human(self) -> None:
        task = {"title": "Cleanup", "objective": "Delete old generated files", "risk_level": "low"}
        result = evaluate_risk(task, {})
        self.assertEqual(result["approval_level"], "human")

    def test_summarize_logs_is_none(self) -> None:
        task = {
            "title": "Log digest",
            "objective": "Summarize logs for weekly review",
            "risk_level": "low",
        }
        result = evaluate_risk(task, {})
        self.assertFalse(result["approval_required"])
        self.assertEqual(result["approval_level"], "none")

    def test_no_human_for_read_only_planning_without_risk_keywords(self) -> None:
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

    def test_reviewer_for_validator_change(self) -> None:
        task = {"title": "Validator", "objective": "Add validator tests for protocol schema"}
        result = evaluate_risk(task, {})
        self.assertEqual(result["approval_level"], "reviewer")

    def test_dashboard_read_only_task_is_reviewer_or_none(self) -> None:
        task = {
            "title": "Dashboard polish",
            "objective": "Read-only dashboard tab for kanban layout",
            "risk_level": "low",
        }
        result = evaluate_risk(task, {})
        self.assertIn(result["approval_level"], {"none", "reviewer"})

    def test_blocked_status(self) -> None:
        task = {"title": "Blocked task", "status": "blocked", "objective": "Cannot proceed"}
        result = evaluate_risk(task, {})
        self.assertEqual(result["approval_level"], "blocked")


if __name__ == "__main__":
    unittest.main()