from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.executor import execute_dispatch  # noqa: E402
from dispatch.preview import build_dispatch_preview, persist_preview  # noqa: E402


class DispatchExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        ignore = shutil.ignore_patterns(".codex", "__pycache__", "*.pyc", "runtime/orchestrator/runs/*")
        shutil.copytree(REPO_ROOT, self.root, ignore=ignore)
        self._seed_task_and_plan()
        self._seed_cli_inventory()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _seed_cli_inventory(self) -> None:
        inv_dir = self.root / "runtime" / "registry"
        inv_dir.mkdir(parents=True, exist_ok=True)
        (inv_dir / "cli_inventory.yaml").write_text(
            yaml.safe_dump(
                {"tools": [{"name": "python", "available": True, "path": sys.executable}]},
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def _seed_task_and_plan(self) -> None:
        task_dir = self.root / "tasks" / "active"
        task_dir.mkdir(parents=True, exist_ok=True)
        task = {
            "id": "T-EXEC",
            "title": "Executor test",
            "owner": "composer",
            "reviewer": "claude",
            "created_by": "composer",
            "status": "ready",
            "phase": "3.2",
            "created_at": "2026-06-12T12:00:00Z",
            "updated_at": "2026-06-12T12:00:00Z",
            "priority": "low",
            "risk_level": "low",
            "requires_human_approval": False,
            "human_approval_checklist": [],
            "objective": "Run safe python test",
            "context": "test",
            "goals": [],
            "non_goals": [],
            "inputs": [],
            "outputs": [],
            "constraints": [],
            "acceptance": [],
            "notes": "",
        }
        (task_dir / "T-EXEC.yaml").write_text(yaml.safe_dump(task, sort_keys=False), encoding="utf-8")
        orch = self.root / "runtime" / "orchestrator"
        orch.mkdir(parents=True, exist_ok=True)
        plan = {
            "run_id": "run-exec",
            "task_id": "T-EXEC",
            "recommended_primary_agent": "composer",
            "recommended_reviewer": "claude",
            "approval_level": "none",
            "approval_required": False,
            "files_to_inspect": [],
        }
        (orch / "latest_plan.json").write_text(json.dumps(plan), encoding="utf-8")
        state = {
            "run_id": "run-exec",
            "task_id": "T-EXEC",
            "task_path": str((task_dir / "T-EXEC.yaml").relative_to(self.root)),
            "plan_path": "runtime/orchestrator/latest_plan.json",
            "approval_level": "none",
            "risk_level": "low",
        }
        (orch / "latest_state.json").write_text(json.dumps(state), encoding="utf-8")

    def _make_preview(self) -> Path:
        preview = build_dispatch_preview(self.root, adapter_id="local-python-exec-test")
        paths = persist_preview(self.root, preview)
        return self.root / paths["preview_path"]

    def test_dry_run_never_calls_subprocess(self) -> None:
        preview_path = self._make_preview()
        with patch("dispatch.executor.subprocess.run") as mock_run:
            result = execute_dispatch(self.root, preview_path, dry_run=True)
            mock_run.assert_not_called()
        self.assertFalse(result.executed)
        self.assertTrue(result.execution_allowed)

    def test_execute_calls_subprocess_after_gates(self) -> None:
        preview_path = self._make_preview()
        mock_completed = subprocess.CompletedProcess(
            args=["python", "-c", "print('agentic-os-executor-test')"],
            returncode=0,
            stdout="agentic-os-executor-test\n",
            stderr="",
        )
        with patch("dispatch.executor.subprocess.run", return_value=mock_completed) as mock_run:
            result = execute_dispatch(
                self.root,
                preview_path,
                operator_execute=True,
                dry_run=False,
            )
            mock_run.assert_called_once()
            _args, kwargs = mock_run.call_args
            self.assertIn("timeout", kwargs)
        self.assertTrue(result.executed)
        self.assertTrue(result.execution_allowed)
        self.assertEqual(result.exit_code, 0)
        self.assertTrue(result.stdout_path.endswith("stdout.log"))

    def test_result_and_event_log_written(self) -> None:
        preview_path = self._make_preview()
        result = execute_dispatch(self.root, preview_path, dry_run=True)
        run_dir = self.root / "runtime" / "dispatch" / "runs" / result.run_id
        self.assertTrue((run_dir / "result.json").exists())
        self.assertTrue((run_dir / "events.jsonl").exists())
        self.assertTrue((self.root / "runtime" / "dispatch" / "latest_result.json").exists())

    def test_blocked_without_execute_flag_via_script(self) -> None:
        preview_path = self._make_preview()
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "execute_dispatch.py"), "--preview", str(preview_path)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(proc.returncode, 2)

    def test_executor_subprocess_isolated_to_executor_module(self) -> None:
        executor_source = (REPO_ROOT / "dispatch" / "executor.py").read_text(encoding="utf-8")
        self.assertIn("import subprocess", executor_source)
        approved_subprocess_modules = frozenset(
            {"executor.py", "worktree_allocator.py", "codex_local_builder.py"}
        )
        for path in (REPO_ROOT / "dispatch").glob("*.py"):
            if path.name in approved_subprocess_modules:
                continue
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("import subprocess", source, msg=path.name)
            self.assertNotIn("subprocess.run", source, msg=path.name)
            self.assertNotIn("subprocess.Popen", source, msg=path.name)

    def test_preview_module_has_no_subprocess(self) -> None:
        source = (REPO_ROOT / "dispatch" / "preview.py").read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", source)

    def test_dashboard_has_no_execution_actions(self) -> None:
        source = (REPO_ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
        dispatch_section = source[source.find("TAB PANEL: DISPATCH") : source.find("TAB PANEL: HEALTH")]
        for forbidden in ("Execute button", "Approve button", "Launch agent", "Run MCP"):
            self.assertNotIn(forbidden, dispatch_section)
        self.assertNotIn('type="submit"', dispatch_section[max(0, dispatch_section.find("dispatch") - 200) :])


if __name__ == "__main__":
    unittest.main()