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

from list_mcps import (
    ALLOWED_MCP_STATUSES,
    MCP_REQUIRED_FIELDS,
    filter_mcps,
    load_mcps_registry,
)


class McpsRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        ignore = shutil.ignore_patterns(".codex", "__pycache__", "*.pyc")
        shutil.copytree(REPO_ROOT, self.root, ignore=ignore)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_mcps_registry_loads(self) -> None:
        registry = load_mcps_registry(self.root)
        self.assertIn("mcps", registry)
        self.assertGreaterEqual(len(registry["mcps"]), 3)

    def test_required_mcp_fields_exist(self) -> None:
        registry = load_mcps_registry(self.root)
        for mcp in registry["mcps"]:
            self.assertEqual(MCP_REQUIRED_FIELDS, set(mcp.keys()))

    def test_invalid_mcp_status_fails_validation(self) -> None:
        registry = load_mcps_registry(self.root)
        registry["mcps"][0]["status"] = "not-a-status"
        path = self.root / "mcps" / "registry.yaml"
        path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(self.root / "scripts" / "validate.py")],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid status", result.stdout.lower())

    def test_planned_mcps_pass_validation(self) -> None:
        result = subprocess.run(
            [sys.executable, str(self.root / "scripts" / "validate.py")],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

    def test_list_mcps_filters_by_status(self) -> None:
        registry = load_mcps_registry(self.root)
        filtered = filter_mcps(registry["mcps"], status="planned")
        self.assertTrue(all(m.get("status") == "planned" for m in filtered))
        self.assertEqual(len(filtered), 3)

    def test_list_mcps_filters_by_agent(self) -> None:
        registry = load_mcps_registry(self.root)
        filtered = filter_mcps(registry["mcps"], agent="codex")
        self.assertTrue(all("codex" in m.get("allowed_agents", []) for m in filtered))
        self.assertGreater(len(filtered), 0)

    def test_list_mcps_cli_json_output(self) -> None:
        result = subprocess.run(
            [sys.executable, str(self.root / "scripts" / "list_mcps.py"), "--root", str(self.root), "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn('"mcps"', result.stdout)

    def test_dashboard_loader_handles_missing_registry(self) -> None:
        (self.root / "mcps" / "registry.yaml").unlink()
        sys.path.insert(0, str(REPO_ROOT))
        from dashboard.app import load_mcps_registry

        data, errors = load_mcps_registry(self.root)
        self.assertIsNone(data)
        self.assertTrue(any("does not exist" in e for e in errors))


class McpsRegistryConstantsTests(unittest.TestCase):
    def test_allowed_statuses_include_planned(self) -> None:
        self.assertIn("planned", ALLOWED_MCP_STATUSES)


if __name__ == "__main__":
    unittest.main()