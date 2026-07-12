"""Phase 3.8B — assignment loop activation tests."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


class DashboardScriptLaunchPathTests(unittest.TestCase):
    """Prove load_composer_assignment_index works under script-style launch path."""

    def test_import_assignment_index_loader_via_script_style_path(self) -> None:
        """Mirrors `python dashboard/app.py`: load app module from file path."""
        app_path = REPO_ROOT / "dashboard" / "app.py"
        # Fresh process-like: ensure ROOT is on path only via app module's own insert
        # Simulate script launch by loading from file with a clean name.
        spec = importlib.util.spec_from_file_location("dashboard_app_script_style", app_path)
        self.assertIsNotNone(spec)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        # Pre-condition: module's top-level must insert repo root so dispatch imports work
        spec.loader.exec_module(mod)
        self.assertTrue(hasattr(mod, "load_composer_assignment_index"))
        self.assertTrue(hasattr(mod, "ROOT_DIR"))
        self.assertEqual(mod.ROOT_DIR.resolve(), REPO_ROOT.resolve())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "runtime" / "dispatch" / "assignments" / "inbox"
            inbox.mkdir(parents=True)
            (inbox / "assign-script-path.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "assignment_id": "assign-script-path",
                        "task_id": "T-SCRIPT-PATH",
                        "title": "Script path test",
                        "goal": "Prove dashboard script import",
                        "base_branch": "main",
                        "base_sha": "a" * 40,
                        "new_branch": "agent/composer/T-SCRIPT-PATH",
                        "allowed_paths": ["docs/**"],
                        "forbidden_operations": ["git_merge"],
                        "acceptance_criteria": ["loads"],
                        "verification_commands": ["python scripts/validate.py"],
                        "timeout": 600,
                        "handoff_path": "handoffs/T-SCRIPT-PATH__composer__to__claude.md",
                        "assigned_by": "claude",
                        "assigned_to": "composer",
                        "status": "pending",
                        "created_at": "2026-07-12T00:00:00Z",
                        "updated_at": "2026-07-12T00:00:00Z",
                        "adapter_id": "composer-restricted",
                        "execution_route": "composer_local_builder",
                        "task_path": "tasks/active/T-SCRIPT-PATH.yaml",
                        "handoff_rel": "handoffs/T-SCRIPT-PATH__composer__to__claude.md",
                    }
                ),
                encoding="utf-8",
            )
            index, errors = mod.load_composer_assignment_index(root)
            self.assertEqual(errors, [])
            self.assertEqual(len(index["pending_only"]), 1)
            self.assertIn("T-SCRIPT-PATH", index["by_task_id"])

    def test_dashboard_app_module_import_works(self) -> None:
        """`python -m dashboard.app` style package import."""
        from dashboard.app import load_composer_assignment_index, ROOT_DIR

        self.assertEqual(ROOT_DIR.resolve(), REPO_ROOT.resolve())
        index, errors = load_composer_assignment_index(REPO_ROOT)
        self.assertIsInstance(index, dict)
        self.assertIsInstance(errors, list)


class AssignmentLifecycleDashboardTests(unittest.TestCase):
    def test_lifecycle_statuses_surface_on_execution_runs(self) -> None:
        from dashboard.app import load_execution_runs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "runtime" / "dispatch" / "assignments" / "inbox"
            outbox = root / "runtime" / "dispatch" / "assignments" / "outbox"
            inbox.mkdir(parents=True)
            outbox.mkdir(parents=True)

            def write_inbox(aid: str, task_id: str, status: str) -> None:
                (inbox / f"{aid}.json").write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "assignment_id": aid,
                            "task_id": task_id,
                            "title": task_id,
                            "goal": "g",
                            "base_branch": "main",
                            "base_sha": "a" * 40,
                            "new_branch": f"agent/composer/{task_id}",
                            "allowed_paths": [],
                            "forbidden_operations": [],
                            "acceptance_criteria": [],
                            "verification_commands": [],
                            "timeout": 60,
                            "handoff_path": f"handoffs/{task_id}__composer__to__claude.md",
                            "assigned_by": "claude",
                            "assigned_to": "composer",
                            "status": status,
                            "created_at": "2026-07-12T00:00:00Z",
                            "updated_at": "2026-07-12T01:00:00Z",
                            "adapter_id": "composer-restricted",
                            "execution_route": "composer_local_builder",
                            "task_path": f"tasks/active/{task_id}.yaml",
                            "handoff_rel": f"handoffs/{task_id}__composer__to__claude.md",
                        }
                    ),
                    encoding="utf-8",
                )

            write_inbox("assign-pending", "T-P", "pending")
            write_inbox("assign-claimed", "T-C", "claimed")
            write_inbox("assign-review", "T-R", "awaiting_review")
            (outbox / "assign-review.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "assignment_id": "assign-review",
                        "task_id": "T-R",
                        "adapter_id": "composer-restricted",
                        "status": "awaiting_review",
                        "finished_at": "2026-07-12T02:00:00Z",
                        "handoff_path": "handoffs/T-R__composer__to__claude.md",
                        "branch_tip_sha": "b" * 40,
                        "branch_name": "agent/composer/T-R",
                    }
                ),
                encoding="utf-8",
            )

            runs, errors = load_execution_runs(root)
            self.assertEqual(errors, [])
            by_task = {r["task_id"]: r for r in runs}
            self.assertEqual(by_task["T-P"]["status"], "assignment_pending")
            self.assertEqual(by_task["T-C"]["status"], "assignment_claimed")
            self.assertEqual(by_task["T-R"]["status"], "assignment_awaiting_review")
            self.assertEqual(
                by_task["T-R"]["handoff_path"],
                "handoffs/T-R__composer__to__claude.md",
            )
            self.assertTrue(by_task["T-R"].get("result_path"))


class AssignmentsCliSmokeTests(unittest.TestCase):
    def test_cli_list_exit_zero(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "assignments.py"), "list", "--json"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertIn("assignments", data)


class IdentityMetadataTests(unittest.TestCase):
    def test_display_name_is_grok_build_45(self) -> None:
        import yaml

        registry = yaml.safe_load(
            (REPO_ROOT / "agents" / "adapter_registry.yaml").read_text(encoding="utf-8")
        )
        entry = next(a for a in registry["adapters"] if a["id"] == "composer-restricted")
        self.assertEqual(entry["display_name"], "Grok Build (Grok 4.5)")
        self.assertEqual(entry["id"], "composer-restricted")
        self.assertEqual(entry["agent_id"], "composer")

        detail = yaml.safe_load(
            (REPO_ROOT / "agents" / "composer_restricted_adapter.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(detail["display_name"], "Grok Build (Grok 4.5)")
        self.assertFalse(detail.get("supports_execution"))


class DogfoodFixturePresenceTests(unittest.TestCase):
    def test_dogfood_fixtures_committed(self) -> None:
        fixture_root = REPO_ROOT / "tests" / "fixtures" / "assignment_loop_dogfood"
        if not fixture_root.is_dir():
            self.skipTest("dogfood fixtures not yet committed (created during closeout)")
        required = (
            "assignment.json",
            "claim.json",
            "result.json",
            "HANDOFF.md",
            "README.md",
        )
        for name in required:
            self.assertTrue((fixture_root / name).is_file(), f"missing {name}")


class DashboardLaunchSmokeTests(unittest.TestCase):
    def test_dashboard_app_py_starts_without_dispatch_import_error(self) -> None:
        """Smoke: importing dashboard.app must not raise ModuleNotFoundError: dispatch."""
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import importlib.util, sys; "
                    f"p=r'{str(REPO_ROOT / 'dashboard' / 'app.py')}'; "
                    "spec=importlib.util.spec_from_file_location('dash_smoke', p); "
                    "m=importlib.util.module_from_spec(spec); "
                    "spec.loader.exec_module(m); "
                    "m.load_composer_assignment_index(m.ROOT_DIR); "
                    "print('OK')"
                ),
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("OK", proc.stdout)


if __name__ == "__main__":
    unittest.main()
