from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


class Phase15CliTests(unittest.TestCase):
    def setUp(self) -> None:
        temp_root = REPO_ROOT / ".tmp-tests"
        temp_root.mkdir(exist_ok=True)
        self.tmp_dir = temp_root / uuid.uuid4().hex
        self.root = self.tmp_dir / "repo"
        ignore = shutil.ignore_patterns(".codex", ".tmp-tests", "__pycache__", "*.pyc")
        shutil.copytree(REPO_ROOT, self.root, ignore=ignore)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

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
            "T-0012",
            "--title",
            "Phase 1.5 CLI task runner",
            "--owner",
            "codex",
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
            "--label",
            "phase-1.5",
        )

        task_path = self.root / "tasks" / "active" / "T-0012.yaml"
        self.assertTrue(task_path.exists())
        task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
        self.assertEqual(task["id"], "T-0012")
        self.assertEqual(task["status"], "ready")
        self.assertEqual(task["risk_level"], "low")
        self.assertFalse(task["requires_human_approval"])
        self.assertEqual(task["reviewer"], "claude")
        self.assertEqual(task["created_by"], "codex")
        self.assertEqual(task["outputs"], ["scripts/create_task.py"])
        self.assertIn("phase-1.5", task["labels"])

    def test_update_task_changes_status_and_moves_done_task(self) -> None:
        self.run_script(
            "create_task.py",
            "--id",
            "T-0013",
            "--title",
            "Move task",
            "--objective",
            "Exercise status movement.",
            "--output",
            "tasks/done/T-0013.yaml",
        )

        self.run_script("update_task.py", "--id", "T-0013", "--status", "done", "--owner", "claude")

        active_path = self.root / "tasks" / "active" / "T-0013.yaml"
        done_path = self.root / "tasks" / "done" / "T-0013.yaml"
        self.assertFalse(active_path.exists())
        self.assertTrue(done_path.exists())
        task = yaml.safe_load(done_path.read_text(encoding="utf-8"))
        self.assertEqual(task["status"], "done")
        self.assertEqual(task["owner"], "claude")

    def test_create_task_emits_schema_v2_fields(self) -> None:
        self.run_script(
            "create_task.py",
            "--id",
            "T-9016",
            "--title",
            "Schema v2 task",
            "--objective",
            "Exercise v2 creation.",
            "--output",
            "tasks/active/T-9016.yaml",
        )

        task = yaml.safe_load((self.root / "tasks" / "active" / "T-9016.yaml").read_text(encoding="utf-8"))
        for deprecated in ("created", "updated", "acceptance_criteria", "handoff_notes"):
            self.assertNotIn(deprecated, task)
        for required in (
            "created_at",
            "updated_at",
            "reviewer",
            "created_by",
            "phase",
            "goals",
            "non_goals",
            "acceptance",
            "notes",
            "human_approval_checklist",
        ):
            self.assertIn(required, task)
        self.assertEqual(task["status"], "ready")
        self.assertEqual(task["priority"], "high")

    def test_create_task_with_human_approval_populates_checklist(self) -> None:
        self.run_script(
            "create_task.py",
            "--id",
            "T-0017",
            "--title",
            "Approval task",
            "--objective",
            "Exercise approval checklist.",
            "--requires-human-approval",
            "--output",
            "tasks/active/T-0017.yaml",
        )

        task = yaml.safe_load((self.root / "tasks" / "active" / "T-0017.yaml").read_text(encoding="utf-8"))
        self.assertTrue(task["requires_human_approval"])
        self.assertTrue(task["human_approval_checklist"])

    def test_update_task_preserves_schema_v2_and_review_reviewer_rule(self) -> None:
        self.run_script(
            "create_task.py",
            "--id",
            "T-0018",
            "--title",
            "Review task",
            "--objective",
            "Exercise review update.",
            "--output",
            "tasks/active/T-0018.yaml",
        )

        self.run_script("update_task.py", "--id", "T-0018", "--status", "review", "--owner", "codex")

        task = yaml.safe_load((self.root / "tasks" / "active" / "T-0018.yaml").read_text(encoding="utf-8"))
        self.assertEqual(task["status"], "review")
        self.assertEqual(task["reviewer"], "claude")
        self.assertNotIn("updated", task)
        self.assertIn("updated_at", task)

    def test_create_task_output_validates_without_task_warnings(self) -> None:
        self.run_script(
            "create_task.py",
            "--id",
            "T-0019",
            "--title",
            "Validated task",
            "--objective",
            "Exercise validator compatibility.",
            "--output",
            "tasks/active/T-0019.yaml",
        )

        result = subprocess.run(
            [sys.executable, str(self.root / "scripts" / "validate.py")],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertNotIn("tasks/active/T-0019.yaml", result.stderr)

    def test_append_log_adds_single_jsonl_event(self) -> None:
        before = (self.root / "logs" / "agent-events.jsonl").read_text(encoding="utf-8").splitlines()

        self.run_script(
            "append_log.py",
            "--agent",
            "codex",
            "--task",
            "T-0012",
            "--event",
            "started",
            "--detail",
            "started Phase 1.5",
            "--ref",
            "tasks/active/T-0012.yaml",
        )

        lines = (self.root / "logs" / "agent-events.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), len(before) + 1)
        event = json.loads(lines[-1])
        self.assertEqual(event["agent"], "codex")
        self.assertEqual(event["task"], "T-0012")
        self.assertEqual(event["event"], "started")
        self.assertEqual(event["ref"], "tasks/active/T-0012.yaml")
        self.assertTrue(event["ts"].endswith("Z"))

    def test_create_handoff_writes_required_sections(self) -> None:
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
