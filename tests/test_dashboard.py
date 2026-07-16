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
    load_execution_runs,
    apply_execution_run_filters,
    generate_dashboard_html,
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

    def test_load_execution_runs_tolerates_missing_runtime(self) -> None:
        runs, errors = load_execution_runs(self.root)
        self.assertEqual(runs, [])
        self.assertEqual(errors, [])

    def test_load_execution_runs_parses_required_metadata(self) -> None:
        run_dir = self.root / "runtime" / "dispatch" / "runs" / "build-test"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "result.json").write_text(
            json.dumps(
                {
                    "run_id": "build-test",
                    "task_id": "T-TEST",
                    "adapter_id": "codex-restricted",
                    "route": "codex_local_builder",
                    "status": "completed_verified",
                    "started_at": "2026-06-30T12:00:00Z",
                    "finished_at": "2026-06-30T12:05:00Z",
                    "worktree_path": "C:/tmp/worktree",
                    "handoff_path": "C:/tmp/worktree/handoffs/T-TEST__codex__to__claude.md",
                    "blocked_reasons": [],
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "verification_results.json").write_text(
            json.dumps(
                {
                    "commands": [
                        {
                            "command": "python scripts/validate.py",
                            "exit_code": 0,
                            "timed_out": False,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        runs, errors = load_execution_runs(self.root)
        self.assertEqual(errors, [])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["task_id"], "T-TEST")
        self.assertEqual(runs[0]["adapter_id"], "codex-restricted")
        self.assertEqual(runs[0]["route"], "codex_local_builder")
        self.assertEqual(runs[0]["status"], "completed_verified")
        self.assertEqual(runs[0]["verification_status"], "passed")
        self.assertEqual(runs[0]["blocked_reasons"], [])
        self.assertEqual(runs[0]["handoff_path"], "C:/tmp/worktree/handoffs/T-TEST__codex__to__claude.md")

    def test_load_execution_runs_reports_malformed_result(self) -> None:
        run_dir = self.root / "runtime" / "dispatch" / "runs" / "bad-run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "result.json").write_text("{not-json", encoding="utf-8")

        runs, errors = load_execution_runs(self.root)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["run_id"], "bad-run")
        self.assertEqual(runs[0]["status"], "unknown")
        self.assertTrue(errors)
        self.assertTrue(runs[0]["errors"])

    def test_load_execution_runs_includes_claim_state_when_claimed(self) -> None:
        run_dir = self.root / "runtime" / "dispatch" / "runs" / "build-claimed"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "result.json").write_text(
            json.dumps(
                {
                    "run_id": "build-claimed",
                    "task_id": "T-TEST",
                    "adapter_id": "codex-restricted",
                    "status": "completed_verified",
                }
            ),
            encoding="utf-8",
        )
        claims_dir = self.root / "runtime" / "dispatch" / "local_builder_claims"
        claims_dir.mkdir(parents=True, exist_ok=True)
        (claims_dir / "T-TEST.json").write_text(
            json.dumps(
                {
                    "task_id": "T-TEST",
                    "run_id": "build-claimed",
                    "claimed_at": "2026-07-01T10:00:00Z",
                }
            ),
            encoding="utf-8",
        )

        runs, errors = load_execution_runs(self.root)
        self.assertEqual(errors, [])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["claim_state"], "claimed")
        self.assertEqual(runs[0]["task_lifecycle_status"], "in_progress")
        self.assertEqual(runs[0]["active_claim_run_id"], "build-claimed")

    def test_load_execution_runs_claim_state_review_pending(self) -> None:
        run_dir = self.root / "runtime" / "dispatch" / "runs" / "build-review"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "result.json").write_text(
            json.dumps(
                {
                    "run_id": "build-review",
                    "task_id": "T-TEST",
                    "adapter_id": "codex-restricted",
                    "status": "completed_verified",
                }
            ),
            encoding="utf-8",
        )
        task_path = self.root / "tasks" / "active" / "T-TEST.yaml"
        task_data = yaml.safe_load(task_path.read_text(encoding="utf-8"))
        task_data["status"] = "review"
        task_path.write_text(yaml.safe_dump(task_data, sort_keys=False), encoding="utf-8")

        runs, _ = load_execution_runs(self.root)
        self.assertEqual(runs[0]["claim_state"], "review_pending")
        self.assertEqual(runs[0]["task_lifecycle_status"], "review")

    def test_apply_execution_run_filters_by_adapter_and_status(self) -> None:
        runs = [
            {"adapter_id": "codex-restricted", "status": "completed_verified"},
            {"adapter_id": "local-python-exec-test", "status": "blocked"},
        ]
        filtered = apply_execution_run_filters(
            runs,
            adapter="codex",
            status="completed_verified",
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["adapter_id"], "codex-restricted")

    def test_execution_runs_tab_renders_claim_state_and_filters(self) -> None:
        import dashboard.app as dashboard_app

        original_root = dashboard_app.ROOT_DIR
        dashboard_app.ROOT_DIR = self.root
        try:
            run_dir = self.root / "runtime" / "dispatch" / "runs" / "build-ui"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "result.json").write_text(
                json.dumps(
                    {
                        "run_id": "build-ui",
                        "task_id": "T-TEST",
                        "adapter_id": "codex-restricted",
                        "status": "completed_verified",
                    }
                ),
                encoding="utf-8",
            )
            html = generate_dashboard_html(
                {
                    "tab": ["execution_runs"],
                    "run_adapter": ["codex-restricted"],
                    "run_status": ["completed_verified"],
                }
            )
            self.assertIn("execution_runs", html)
            self.assertIn("read-only", html.lower())
            self.assertIn("Claim / Lifecycle", html)
            self.assertIn("released", html.lower())
            self.assertIn("codex-restricted", html)
            self.assertIn('name="run_adapter"', html)
            self.assertIn('name="run_status"', html)
        finally:
            dashboard_app.ROOT_DIR = original_root

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
