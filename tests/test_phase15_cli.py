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


class Phase15CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        ignore = shutil.ignore_patterns(".codex", "__pycache__", "*.pyc")
        shutil.copytree(REPO_ROOT, self.root, ignore=ignore)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_script(self, script: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.root / "scripts" / script), "--root", str(self.root), *args],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=True,
        )

    def test_create_task_writes_valid_active_task(self) -> None:
        self.run_script(
            "create_task.py",
            "--id",
            "T-9912",
            "--title",
            "Phase 1.5 CLI task runner",
            "--owner",
            "codex",
            "--reviewer",
            "claude",
            "--objective",
            "Add minimal file-based CLI helpers.",
            "--input",
            "docs/TASK_SCHEMA.md",
            "--output",
            "scripts/create_task.py",
            "--constraint",
            "No new dependencies.",
            "--acceptance",
            "Task YAML validates.",
            "--handoff-notes",
            "Hand off to claude for review.",
            "--human-approval-checklist-item",
            "Confirm scripts change is approved.",
            "--label",
            "phase-1.5",
        )

        task_path = self.root / "tasks" / "active" / "T-9912.yaml"
        self.assertTrue(task_path.exists())
        task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
        self.assertEqual(task["id"], "T-9912")
        self.assertEqual(task["status"], "ready")
        self.assertEqual(task["reviewer"], "claude")
        self.assertEqual(task["risk_level"], "medium")
        self.assertTrue(task["requires_human_approval"])
        self.assertEqual(task["outputs"], ["scripts/create_task.py"])
        self.assertIn("phase-1.5", task["labels"])

    def test_update_task_changes_status_and_moves_done_task(self) -> None:
        self.run_script(
            "create_task.py",
            "--id",
            "T-0013",
            "--title",
            "Move task",
            "--reviewer",
            "claude",
            "--objective",
            "Exercise status movement.",
            "--output",
            "tasks/done/T-0013.yaml",
            "--human-approval-checklist-item",
            "Confirm done path output is approved.",
        )

        self.run_script("update_task.py", "--id", "T-0013", "--status", "done")

        active_path = self.root / "tasks" / "active" / "T-0013.yaml"
        done_path = self.root / "tasks" / "done" / "T-0013.yaml"
        self.assertFalse(active_path.exists())
        self.assertTrue(done_path.exists())
        task = yaml.safe_load(done_path.read_text(encoding="utf-8"))
        self.assertEqual(task["status"], "done")
        self.assertEqual(task["owner"], "codex")

    def test_append_log_adds_single_jsonl_event(self) -> None:
        before = (self.root / "logs" / "agent-events.jsonl").read_text(encoding="utf-8").splitlines()

        self.run_script(
            "append_log.py",
            "--agent",
            "codex",
            "--task",
            "T-0012",
            "--type",
            "note",
            "--text",
            "started Phase 1.5",
            "--ref",
            "tasks/active/T-0012.yaml",
        )

        lines = (self.root / "logs" / "agent-events.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), len(before) + 1)
        event = json.loads(lines[-1])
        self.assertEqual(event["agent"], "codex")
        self.assertEqual(event["task_id"], "T-0012")
        self.assertEqual(event["type"], "note")
        self.assertEqual(event["ref"], "tasks/active/T-0012.yaml")
        self.assertTrue(event["ts"].endswith("Z"))

    def test_create_handoff_writes_required_sections(self) -> None:
        self.run_script(
            "create_task.py",
            "--id",
            "T-0099",
            "--title",
            "Handoff task",
            "--reviewer",
            "claude",
            "--objective",
            "Exercise handoff creation.",
            "--output",
            "tasks/active/T-0099.yaml",
        )
        self.run_script(
            "create_handoff.py",
            "--task",
            "T-0099",
            "--from-agent",
            "codex",
            "--to-agent",
            "claude",
            "--status",
            "review",
            "--what-i-did",
            "Added Phase 1.5 CLI helpers.",
            "--what-remains",
            "Claude review.",
            "--verify",
            "Run python -m unittest.",
            "--next-action",
            "Review the scripts.",
        )

        handoff_path = self.root / "handoffs" / "T-0099__codex__to__claude.md"
        text = handoff_path.read_text(encoding="utf-8")
        self.assertIn("# Handoff: T-0099", text)
        for section in (
            "## What I Did",
            "## What Remains",
            "## Decisions Made",
            "## Open Questions",
            "## How to Verify My Work",
            "## Risks / Caveats",
            "## Recommended Next Action for Receiver",
        ):
            self.assertIn(section, text)

    def test_list_tasks_includes_tasks_from_all_state_directories(self) -> None:
        self.run_script(
            "create_task.py",
            "--id",
            "T-0014",
            "--title",
            "Visible task",
            "--reviewer",
            "claude",
            "--objective",
            "Show up in task list.",
            "--output",
            "tasks/active/T-0014.yaml",
        )

        result = self.run_script("list_tasks.py")

        self.assertIn("T-0014", result.stdout)
        self.assertIn("active", result.stdout)
        self.assertIn("Visible task", result.stdout)


if __name__ == "__main__":
    unittest.main()
