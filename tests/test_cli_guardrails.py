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


class CliGuardrailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        ignore = shutil.ignore_patterns(".codex", "__pycache__", "*.pyc")
        shutil.copytree(REPO_ROOT, self.root, ignore=ignore)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_script(self, script: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.root / "scripts" / script), "--root", str(self.root), *args],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=check,
        )

    def test_create_task_emits_v2_fields_only(self) -> None:
        self.run_script(
            "create_task.py",
            "--id",
            "T-9101",
            "--title",
            "Schema v2 task",
            "--owner",
            "codex",
            "--reviewer",
            "claude",
            "--objective",
            "Emit v2 fields.",
            "--output",
            "tasks/active/T-9101.yaml",
            "--acceptance",
            "No v1 fields.",
            "--goal",
            "Emit v2 fields.",
            "--non-goal",
            "Emit v1 fields.",
        )
        task = yaml.safe_load((self.root / "tasks" / "active" / "T-9101.yaml").read_text(encoding="utf-8"))
        for key in ("created", "updated", "acceptance_criteria", "handoff_notes"):
            self.assertNotIn(key, task)
        for key in ("created_at", "updated_at", "reviewer", "created_by", "phase", "goals", "non_goals", "acceptance", "notes"):
            self.assertIn(key, task)
        self.assertEqual(task["reviewer"], "claude")
        self.assertEqual(task["created_by"], "codex")
        self.assertEqual(task["status"], "ready")
        self.assertEqual(task["priority"], "high")

    def test_create_task_auto_escalates_risky_outputs_and_requires_checklist(self) -> None:
        blocked = self.run_script(
            "create_task.py",
            "--id",
            "T-9102",
            "--title",
            "Risky task",
            "--reviewer",
            "claude",
            "--objective",
            "Touch scripts.",
            "--output",
            "scripts/create_task.py",
            check=False,
        )
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("human approval checklist", blocked.stderr)

        self.run_script(
            "create_task.py",
            "--id",
            "T-9102",
            "--title",
            "Risky task",
            "--reviewer",
            "claude",
            "--objective",
            "Touch scripts.",
            "--output",
            "scripts/create_task.py",
            "--human-approval-checklist-item",
            "Confirm scripts change is approved.",
        )
        task = yaml.safe_load((self.root / "tasks" / "active" / "T-9102.yaml").read_text(encoding="utf-8"))
        self.assertEqual(task["risk_level"], "medium")
        self.assertTrue(task["requires_human_approval"])
        self.assertEqual(task["human_approval_checklist"], ["Confirm scripts change is approved."])

    def test_create_task_rejects_owner_equal_reviewer(self) -> None:
        result = self.run_script(
            "create_task.py",
            "--id",
            "T-9103",
            "--title",
            "Bad reviewer",
            "--owner",
            "codex",
            "--reviewer",
            "codex",
            "--objective",
            "Reject same owner/reviewer.",
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reviewer must differ from owner", result.stderr)

    def test_update_task_rejects_review_without_reviewer(self) -> None:
        path = self.root / "tasks" / "active" / "T-9104.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "id": "T-9104",
                    "title": "Missing reviewer",
                    "status": "ready",
                    "owner": "codex",
                    "created_by": "codex",
                    "created_at": "2026-05-23T00:00:00Z",
                    "updated_at": "2026-05-23T00:00:00Z",
                    "phase": "1.5",
                    "priority": "high",
                    "risk_level": "low",
                    "requires_human_approval": False,
                    "objective": "Missing reviewer.",
                    "context": "Missing reviewer.",
                    "goals": ["Missing reviewer."],
                    "non_goals": [],
                    "inputs": ["README.md"],
                    "outputs": ["tasks/active/T-9104.yaml"],
                    "constraints": ["None."],
                    "acceptance": ["Rejected."],
                    "human_approval_checklist": [],
                    "notes": "None.",
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        result = self.run_script("update_task.py", "--id", "T-9104", "--status", "review", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reviewer is required", result.stderr)

    def test_append_log_rejects_unknown_type_unless_forced(self) -> None:
        rejected = self.run_script(
            "append_log.py",
            "--agent",
            "codex",
            "--task",
            "T-9105",
            "--type",
            "surprise",
            check=False,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("unknown event type", rejected.stderr)

        forced = self.run_script(
            "append_log.py",
            "--agent",
            "codex",
            "--task",
            "T-9105",
            "--type",
            "surprise",
            "--force",
            check=False,
        )
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertIn("Warning", forced.stderr)

    def test_t0012_rollback_shape(self) -> None:
        active = self.root / "tasks" / "active" / "T-0012.yaml"
        done = self.root / "tasks" / "done" / "T-0012.yaml"
        self.assertTrue(active.exists())
        self.assertFalse(done.exists())
        task = yaml.safe_load(active.read_text(encoding="utf-8"))
        self.assertEqual(task["status"], "review")
        self.assertEqual(task["owner"], "codex")
        self.assertEqual(task["reviewer"], "claude")
        self.assertTrue(task["human_approval_checklist"])

        events = [
            json.loads(line)
            for line in (self.root / "logs" / "agent-events.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertTrue(
            any(
                event.get("type") == "status_changed"
                and event.get("task_id") == "T-0012"
                and event.get("ref") == "decisions/ADR-0003-phase-1-protocol-corrections.md"
                for event in events
            )
        )
