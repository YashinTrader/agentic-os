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

from list_teams import load_teams_registry

TEAM_REQUIRED_FIELDS = {
    "id",
    "name",
    "description",
    "purpose",
    "orchestrator",
    "members",
    "default_reviewer",
    "required_skills",
    "optional_skills",
    "allowed_mcps",
    "approval_policy",
    "task_suitability",
    "status",
    "notes",
}


class TeamsRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        ignore = shutil.ignore_patterns(".codex", "__pycache__", "*.pyc")
        shutil.copytree(REPO_ROOT, self.root, ignore=ignore)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_teams_registry_loads(self) -> None:
        registry = load_teams_registry(self.root)
        self.assertIn("teams", registry)
        self.assertGreaterEqual(len(registry["teams"]), 5)

    def test_required_team_fields_exist(self) -> None:
        registry = load_teams_registry(self.root)
        for team in registry["teams"]:
            self.assertEqual(TEAM_REQUIRED_FIELDS, set(team.keys()))

    def test_invalid_team_status_fails_validation(self) -> None:
        registry = load_teams_registry(self.root)
        registry["teams"][0]["status"] = "invalid-status"
        path = self.root / "teams" / "registry.yaml"
        path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(self.root / "scripts" / "validate.py")],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid status", result.stdout.lower())

    def test_missing_skill_cross_reference_fails(self) -> None:
        registry = load_teams_registry(self.root)
        registry["teams"][0]["required_skills"] = ["nonexistent-skill"]
        path = self.root / "teams" / "registry.yaml"
        path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(self.root / "scripts" / "validate.py")],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("unknown skill", result.stdout.lower())

    def test_missing_role_cross_reference_fails(self) -> None:
        registry = load_teams_registry(self.root)
        registry["teams"][0]["members"][0]["role"] = "nonexistent-role"
        path = self.root / "teams" / "registry.yaml"
        path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(self.root / "scripts" / "validate.py")],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("not found in roles/registry.yaml", result.stdout.lower())

    def test_list_teams_filters_by_status(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(self.root / "scripts" / "list_teams.py"),
                "--root",
                str(self.root),
                "--status",
                "active",
                "--json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn('"teams"', result.stdout)

    def test_missing_mcp_cross_reference_fails(self) -> None:
        registry = load_teams_registry(self.root)
        registry["teams"][0]["allowed_mcps"] = ["nonexistent-mcp"]
        path = self.root / "teams" / "registry.yaml"
        path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(self.root / "scripts" / "validate.py")],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("unknown mcp", result.stdout.lower())

    def test_teams_tab_rejects_path_traversal_suggest_task(self) -> None:
        import dashboard.app as app_module

        original_root = app_module.ROOT_DIR
        try:
            app_module.ROOT_DIR = self.root
            html = app_module.generate_dashboard_html(
                {"tab": ["teams"], "suggest_task": ["../../../outside"]}
            )
            self.assertIn("Teams Registry", html)
            self.assertIn("No suggestions for selected task.", html)
            # Suggestion panel must not render scored rows for traversal input.
            self.assertNotIn("<th>Score</th>", html)
            self.assertNotIn("outside.yaml", html)
        finally:
            app_module.ROOT_DIR = original_root

    def test_dashboard_loader_handles_missing_teams_registry(self) -> None:
        (self.root / "teams" / "registry.yaml").unlink()
        sys.path.insert(0, str(REPO_ROOT))
        from dashboard.app import load_teams_registry

        data, errors = load_teams_registry(self.root)
        self.assertIsNone(data)
        self.assertTrue(any("does not exist" in e for e in errors))


if __name__ == "__main__":
    unittest.main()