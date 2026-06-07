from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from suggest_team import suggest_teams


class TeamSuggestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        ignore = shutil.ignore_patterns(".codex", "__pycache__", "*.pyc")
        shutil.copytree(REPO_ROOT, self.root, ignore=ignore)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_suggest_team_by_dashboard_skill(self) -> None:
        suggestions = suggest_teams(self.root, skill="build-streamlit-dashboard", limit=3)
        self.assertTrue(suggestions)
        self.assertEqual(suggestions[0]["team_id"], "dashboard-team")

    def test_suggest_team_by_python_cli_skill(self) -> None:
        suggestions = suggest_teams(self.root, skill="implement-python-cli", limit=3)
        self.assertTrue(suggestions)
        top_ids = [s["team_id"] for s in suggestions]
        self.assertIn("coding-team", top_ids)

    def test_suggest_team_for_dashboard_task(self) -> None:
        task = {
            "id": "T-TEST-DASH",
            "title": "Improve dashboard kanban layout",
            "objective": "Polish the Streamlit dashboard kanban board UI.",
            "risk_level": "medium",
            "labels": ["dashboard"],
        }
        task_path = self.root / "tasks" / "active" / "T-TEST-DASH.yaml"
        task_path.write_text(yaml.safe_dump(task, sort_keys=False), encoding="utf-8")

        suggestions = suggest_teams(self.root, task_path=task_path, limit=3)
        self.assertTrue(suggestions)
        self.assertEqual(suggestions[0]["team_id"], "dashboard-team")

    def test_suggest_team_for_cli_task(self) -> None:
        task = {
            "id": "T-TEST-CLI",
            "title": "Add Python CLI validator script",
            "objective": "Implement a new scripts/ CLI utility with unittest coverage.",
            "risk_level": "medium",
            "labels": ["cli", "python"],
        }
        task_path = self.root / "tasks" / "active" / "T-TEST-CLI.yaml"
        task_path.write_text(yaml.safe_dump(task, sort_keys=False), encoding="utf-8")

        suggestions = suggest_teams(self.root, task_path=task_path, limit=3)
        self.assertTrue(suggestions)
        top_ids = [s["team_id"] for s in suggestions]
        self.assertIn("coding-team", top_ids)

    def test_suggest_team_is_deterministic(self) -> None:
        first = suggest_teams(self.root, skill="build-streamlit-dashboard", limit=3)
        second = suggest_teams(self.root, skill="build-streamlit-dashboard", limit=3)
        self.assertEqual(first, second)

    def test_suggest_team_cli_json_output(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(self.root / "scripts" / "suggest_team.py"),
                "--root",
                str(self.root),
                "--skill",
                "build-streamlit-dashboard",
                "--json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("dashboard-team", result.stdout)


if __name__ == "__main__":
    unittest.main()