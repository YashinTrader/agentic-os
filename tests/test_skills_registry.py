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

from list_skills import (
    ALLOWED_SKILL_APPROVAL_LEVELS,
    SKILL_REQUIRED_FIELDS,
    filter_skills,
    load_skills_registry,
)


class SkillsRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        ignore = shutil.ignore_patterns(".codex", "__pycache__", "*.pyc")
        shutil.copytree(REPO_ROOT, self.root, ignore=ignore)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_skills_registry_loads(self) -> None:
        registry = load_skills_registry(self.root)
        self.assertIn("skills", registry)
        self.assertGreaterEqual(len(registry["skills"]), 4)

    def test_required_skill_fields_exist(self) -> None:
        registry = load_skills_registry(self.root)
        for skill in registry["skills"]:
            self.assertEqual(SKILL_REQUIRED_FIELDS, set(skill.keys()))

    def test_invalid_skill_status_fails_validation(self) -> None:
        registry = load_skills_registry(self.root)
        registry["skills"][0]["status"] = "actve"
        path = self.root / "skills" / "registry.yaml"
        path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(self.root / "scripts" / "validate.py")],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid status", result.stdout.lower())

    def test_invalid_approval_level_fails_validation(self) -> None:
        registry = load_skills_registry(self.root)
        registry["skills"][0]["approval_level"] = "invalid-approval"
        path = self.root / "skills" / "registry.yaml"
        path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(self.root / "scripts" / "validate.py")],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid approval_level", result.stdout.lower())

    def test_list_skills_filters_by_agent(self) -> None:
        registry = load_skills_registry(self.root)
        filtered = filter_skills(registry["skills"], agent="codex")
        self.assertTrue(all("codex" in s.get("allowed_agents", []) for s in filtered))
        self.assertGreater(len(filtered), 0)

    def test_list_skills_filters_by_risk(self) -> None:
        registry = load_skills_registry(self.root)
        filtered = filter_skills(registry["skills"], risk="low")
        self.assertTrue(all(s.get("risk_level") == "low" for s in filtered))
        self.assertEqual(len(filtered), 1)

    def test_list_skills_cli_json_output(self) -> None:
        result = subprocess.run(
            [sys.executable, str(self.root / "scripts" / "list_skills.py"), "--root", str(self.root), "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn('"skills"', result.stdout)

    def test_dashboard_loader_handles_missing_registry(self) -> None:
        (self.root / "skills" / "registry.yaml").unlink()
        sys.path.insert(0, str(REPO_ROOT))
        from dashboard.app import load_skills_registry

        data, errors = load_skills_registry(self.root)
        self.assertIsNone(data)
        self.assertTrue(any("does not exist" in e for e in errors))


class SkillsRegistryConstantsTests(unittest.TestCase):
    def test_allowed_approval_levels(self) -> None:
        self.assertEqual(ALLOWED_SKILL_APPROVAL_LEVELS, {"none", "reviewer", "human", "blocked"})


if __name__ == "__main__":
    unittest.main()