from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from orchestrator.graph import run_orchestration
from orchestrator.loaders import safe_task_path
from orchestrator.nodes import classify_task, load_task, suggest_team


class OrchestratorGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        ignore = shutil.ignore_patterns(".codex", "__pycache__", "*.pyc", "runtime/orchestrator/runs/*")
        shutil.copytree(REPO_ROOT, self.root, ignore=ignore)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_task(self, name: str, payload: dict) -> Path:
        path = self.root / "tasks" / "active" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        return path

    def test_load_task_valid(self) -> None:
        path = self._write_task(
            "T-DASH-TEST.yaml",
            {
                "id": "T-DASH-TEST",
                "title": "Improve Streamlit dashboard kanban",
                "objective": "Polish dashboard UI",
                "status": "ready",
                "owner": "composer",
                "labels": ["dashboard"],
                "risk_level": "low",
            },
        )
        state = {
            "task_path": str(path),
            "repo_root": str(self.root),
            "run_id": "run-test",
            "dry_run": True,
        }
        updates = load_task(state)
        self.assertEqual(updates["task_id"], "T-DASH-TEST")
        merged = {**state, **updates}
        classified = classify_task(merged)
        self.assertIn("build-streamlit-dashboard", classified["required_skills"])

    def test_load_task_missing_graceful(self) -> None:
        with self.assertRaises(FileNotFoundError):
            safe_task_path(self.root, "tasks/active/DOES-NOT-EXIST.yaml")

    def test_suggest_team_dashboard_task(self) -> None:
        path = self._write_task(
            "T-DASH-TEST.yaml",
            {
                "id": "T-DASH-TEST",
                "title": "Dashboard kanban improvements",
                "objective": "Build Streamlit dashboard features",
                "status": "ready",
                "owner": "composer",
                "labels": ["dashboard"],
                "risk_level": "medium",
            },
        )
        state = run_orchestration(self.root, str(path.relative_to(self.root)), dry_run=True, no_log=True)
        self.assertEqual(state.selected_team, "dashboard-team")

    def test_suggest_team_cli_task(self) -> None:
        path = self._write_task(
            "T-CLI-TEST.yaml",
            {
                "id": "T-CLI-TEST",
                "title": "Add Python CLI validator",
                "objective": "Implement scripts/ CLI utility with unittest",
                "status": "ready",
                "owner": "codex",
                "labels": ["cli", "python"],
                "risk_level": "medium",
            },
        )
        state = run_orchestration(self.root, str(path.relative_to(self.root)), dry_run=True, no_log=True)
        self.assertIn(state.selected_team, {"coding-team", "dashboard-team"})

    def test_graph_end_to_end_writes_outputs(self) -> None:
        path = self._write_task(
            "T-E2E.yaml",
            {
                "id": "T-E2E",
                "title": "Registry validator improvement",
                "objective": "Improve validator for protocol schema",
                "status": "ready",
                "owner": "composer",
                "risk_level": "low",
            },
        )
        state = run_orchestration(self.root, str(path.relative_to(self.root)), dry_run=False, no_log=True)
        self.assertFalse(state.errors)
        plan_path = Path(state.plan_path)
        ctx_path = Path(state.context_pack_path)
        self.assertTrue(plan_path.exists())
        self.assertTrue(ctx_path.exists())

    def test_cli_json_output(self) -> None:
        path = self._write_task(
            "T-JSON.yaml",
            {
                "id": "T-JSON",
                "title": "CLI test",
                "objective": "Python script work",
                "status": "ready",
                "owner": "codex",
                "risk_level": "low",
            },
        )
        rel = str(path.relative_to(self.root))
        result = subprocess.run(
            [
                sys.executable,
                str(self.root / "scripts" / "orchestrate_task.py"),
                "--root",
                str(self.root),
                "--task",
                rel,
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)
        self.assertEqual(data["task_id"], "T-JSON")

    def test_dashboard_loader_missing_plan(self) -> None:
        orch_dir = self.root / "runtime" / "orchestrator"
        orch_dir.mkdir(parents=True, exist_ok=True)
        for name in ("latest_plan.json", "latest_state.json"):
            path = orch_dir / name
            if path.exists():
                path.unlink()
        from dashboard.app import load_orchestrator_latest

        plan, state, errors = load_orchestrator_latest(self.root)
        self.assertIsNone(plan)
        self.assertIsNone(state)


if __name__ == "__main__":
    unittest.main()