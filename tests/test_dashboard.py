from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

# We will import the parsing functions directly from dashboard.app
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.app import (
    load_all_tasks,
    load_events,
    load_handoffs,
    load_adrs,
    get_health_metrics,
    append_note_event,
    update_task_file,
    create_task_file,
)



class TestDashboardParsing(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        (self.root / "tasks" / "active").mkdir(parents=True, exist_ok=True)
        (self.root / "tasks" / "done").mkdir(parents=True, exist_ok=True)
        (self.root / "tasks" / "blocked").mkdir(parents=True, exist_ok=True)
        (self.root / "handoffs").mkdir(parents=True, exist_ok=True)
        (self.root / "decisions").mkdir(parents=True, exist_ok=True)
        (self.root / "logs").mkdir(parents=True, exist_ok=True)

        # Create dummy task in schema v2
        self.dummy_task = {
            "id": "T-TEST",
            "title": "Test Dashboard Functionality",
            "owner": "antigravity",
            "reviewer": "human",
            "created_by": "antigravity",
            "status": "in_progress",
            "phase": "1.0",
            "created_at": "2026-05-23T08:00:00Z",
            "updated_at": "2026-05-23T09:00:00Z",
            "priority": "low",
            "risk_level": "low",
            "requires_human_approval": False,
            "objective": "Verify dashboard works under tests.",
            "context": "Verification purposes.",
            "goals": ["Verify parsing."],
            "non_goals": ["Do actual work."],
            "inputs": ["README.md"],
            "outputs": ["app.py"],
            "constraints": ["Keep it clean."],
            "acceptance": ["Tests pass."],
            "human_approval_checklist": [],
            "notes": "None.",
        }
        with open(self.root / "tasks" / "active" / "T-TEST.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(self.dummy_task, f, sort_keys=False)

        # Create dummy events following ADR-0004 Standard Vocabulary
        self.events = [
            {"ts": "2026-05-23T08:00:00Z", "agent": "antigravity", "task_id": "T-TEST", "type": "task_created", "detail": "Created"},
            {"ts": "2026-05-23T09:00:00Z", "agent": "antigravity", "task_id": "T-TEST", "type": "status_changed", "from": "ready", "to": "in_progress"},
        ]
        with open(self.root / "logs" / "agent-events.jsonl", "w", encoding="utf-8") as f:
            for ev in self.events:
                f.write(json.dumps(ev) + "\n")

        # Create dummy handoff and ADR
        with open(self.root / "handoffs" / "T-TEST__gemini__to__claude.md", "w", encoding="utf-8") as f:
            f.write("# Handoff: T-TEST\n**From:** gemini\n**To:** claude\n")
        with open(self.root / "handoffs" / "README.md", "w", encoding="utf-8") as f:
            f.write("# Handoffs README\n")

        with open(self.root / "decisions" / "ADR-0001-test.md", "w", encoding="utf-8") as f:
            f.write("# ADR-0001: Test Decision\n**Status:** Accepted\n")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_load_all_tasks(self) -> None:
        tasks, errors = load_all_tasks(self.root)
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["id"], "T-TEST")
        self.assertEqual(tasks[0]["status"], "in_progress")
        self.assertEqual(tasks[0]["reviewer"], "human")
        self.assertEqual(tasks[0]["priority"], "low")

    def test_load_events(self) -> None:
        events, errors = load_events(self.root)
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]["type"], "status_changed")

    def test_load_handoffs(self) -> None:
        handoffs = load_handoffs(self.root)
        # Should exclude README.md
        self.assertEqual(len(handoffs), 1)
        self.assertEqual(handoffs[0].name, "T-TEST__gemini__to__claude.md")

    def test_load_adrs(self) -> None:
        adrs = load_adrs(self.root)
        self.assertEqual(len(adrs), 1)
        self.assertEqual(adrs[0].name, "ADR-0001-test.md")

    def test_get_health_metrics(self) -> None:
        metrics = get_health_metrics(self.root)
        self.assertEqual(metrics["active_count"], 1)
        self.assertEqual(metrics["blocked_count"], 0)
        self.assertEqual(metrics["done_count"], 0)
        self.assertEqual(metrics["last_event_ts"], "2026-05-23T09:00:00Z")
        self.assertEqual(metrics["tasks_state"], "ok")
        self.assertEqual(metrics["events_state"], "ok")

    def test_append_note_event(self) -> None:
        append_note_event(self.root, "human", "T-TEST", "This is a test comment")
        events, _ = load_events(self.root)
        self.assertEqual(len(events), 3)
        self.assertEqual(events[2]["type"], "note")
        self.assertEqual(events[2]["task_id"], "T-TEST")
        self.assertEqual(events[2]["text"], "This is a test comment")

    def test_update_task_file(self) -> None:
        # Move status to blocked, and change owner/reviewer
        update_task_file(self.root, "T-TEST", "blocked", "claude", "human", "Blocked notes.")
        
        # Check files are moved/updated correctly
        active_path = self.root / "tasks" / "active" / "T-TEST.yaml"
        blocked_path = self.root / "tasks" / "blocked" / "T-TEST.yaml"
        
        self.assertFalse(active_path.exists())
        self.assertTrue(blocked_path.exists())
        
        data = yaml.safe_load(blocked_path.read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "blocked")
        self.assertEqual(data["owner"], "claude")
        self.assertEqual(data["reviewer"], "human")
        self.assertEqual(data["notes"], "Blocked notes.")
        
        # Event check (should log status_changed and task_assigned)
        events, _ = load_events(self.root)
        self.assertEqual(len(events), 4)
        self.assertEqual(events[2]["type"], "status_changed")
        self.assertEqual(events[2]["to"], "blocked")
        self.assertEqual(events[3]["type"], "task_assigned")
        self.assertEqual(events[3]["to"], "claude")

    def test_create_task_file(self) -> None:
        new_id = create_task_file(
            self.root, "New Dashboard Task", "antigravity", "human", "Create a dashboard",
            "Context", "1.6", "high", "low", ["Goal 1"], ["Criteria 1"]
        )
        self.assertEqual(new_id, "T-0001") # Since T-TEST isn't standard format T-NNNN, standard should default next to T-0001
        
        new_path = self.root / "tasks" / "active" / "T-0001.yaml"
        self.assertTrue(new_path.exists())
        
        data = yaml.safe_load(new_path.read_text(encoding="utf-8"))
        self.assertEqual(data["id"], "T-0001")
        self.assertEqual(data["title"], "New Dashboard Task")
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["owner"], "antigravity")
        self.assertEqual(data["priority"], "high")
        self.assertEqual(data["goals"], ["Goal 1"])
        
        events, _ = load_events(self.root)
        self.assertEqual(len(events), 3)
        self.assertEqual(events[2]["type"], "task_created")
        self.assertEqual(events[2]["task_id"], "T-0001")


if __name__ == "__main__":
    unittest.main()
