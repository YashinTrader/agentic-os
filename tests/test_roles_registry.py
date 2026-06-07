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

from list_roles import ALLOWED_ROLE_APPROVAL_LEVELS, load_roles_registry

ROLE_REQUIRED_FIELDS = {
    "id",
    "name",
    "description",
    "responsibilities",
    "allowed_agents",
    "required_skills",
    "optional_skills",
    "allowed_mcps",
    "risk_level",
    "approval_level",
    "can_delegate",
    "can_review",
    "can_execute",
    "notes",
}


class RolesRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        ignore = shutil.ignore_patterns(".codex", "__pycache__", "*.pyc")
        shutil.copytree(REPO_ROOT, self.root, ignore=ignore)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_roles_registry_loads(self) -> None:
        registry = load_roles_registry(self.root)
        self.assertIn("roles", registry)
        self.assertGreaterEqual(len(registry["roles"]), 8)

    def test_required_role_fields_exist(self) -> None:
        registry = load_roles_registry(self.root)
        for role in registry["roles"]:
            self.assertEqual(ROLE_REQUIRED_FIELDS, set(role.keys()))

    def test_invalid_role_approval_level_fails_validation(self) -> None:
        registry = load_roles_registry(self.root)
        registry["roles"][0]["approval_level"] = "invalid"
        path = self.root / "roles" / "registry.yaml"
        path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(self.root / "scripts" / "validate.py")],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid approval_level", result.stdout.lower())

    def test_list_roles_filters_by_agent(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(self.root / "scripts" / "list_roles.py"),
                "--root",
                str(self.root),
                "--agent",
                "claude",
                "--json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn('"roles"', result.stdout)

    def test_missing_mcp_cross_reference_fails(self) -> None:
        registry = load_roles_registry(self.root)
        registry["roles"][0]["allowed_mcps"] = ["nonexistent-mcp"]
        path = self.root / "roles" / "registry.yaml"
        path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(self.root / "scripts" / "validate.py")],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("unknown mcp", result.stdout.lower())

    def test_dashboard_loader_handles_missing_roles_registry(self) -> None:
        (self.root / "roles" / "registry.yaml").unlink()
        sys.path.insert(0, str(REPO_ROOT))
        from dashboard.app import load_roles_registry

        data, errors = load_roles_registry(self.root)
        self.assertIsNone(data)
        self.assertTrue(any("does not exist" in e for e in errors))


class RolesRegistryConstantsTests(unittest.TestCase):
    def test_allowed_approval_levels(self) -> None:
        self.assertEqual(ALLOWED_ROLE_APPROVAL_LEVELS, {"none", "reviewer", "human", "blocked"})


if __name__ == "__main__":
    unittest.main()