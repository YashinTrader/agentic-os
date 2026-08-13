from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dispatch.orchestrator_pokes import write_orchestrator_poke
from orchestrator.claude_event_consumer import ClaudeEventConsumer, load_watcher_status


class ClaudeEventConsumerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir="C:/tmp")
        self.root = Path(self.tmp.name)
        self.poke, errors = write_orchestrator_poke(
            self.root, source="composer", assignment_id="assign-1",
            task_id="T-1", event="assignment_completed"
        )
        self.assertEqual(errors, [])

    def tearDown(self):
        self.tmp.cleanup()

    def test_lifecycle_records_genuine_activity_and_resolves(self):
        consumer = ClaudeEventConsumer(self.root, processor=lambda **_: {
            "status": "completed", "pid": 4242, "session_id": "sess-1",
            "verdict": "accepted", "assignment_status": "accepted"
        })
        report = consumer.process_once()
        self.assertEqual(report["status"], "resolved")
        self.assertEqual(report["transitions"], [
            "pending", "claimed", "review_starting", "review_running", "resolved"
        ])
        status = load_watcher_status(self.root)
        self.assertEqual(status["pid"], 4242)
        self.assertEqual(status["claude_session_id"], "sess-1")
        self.assertEqual(status["last_verdict"], "accepted")
        self.assertFalse(Path(self.root / self.poke["source_path"]).exists())

    def test_fingerprint_deduplicates_terminal_event(self):
        calls = []
        processor = lambda **kw: calls.append(kw) or {
            "status": "completed", "pid": 1, "session_id": "s", "verdict": "accepted"
        }
        consumer = ClaudeEventConsumer(self.root, processor=processor)
        consumer.process_once()
        duplicate, _ = write_orchestrator_poke(
            self.root, source="composer", assignment_id="assign-1",
            task_id="T-1", event="assignment_completed"
        )
        report = consumer.process_once()
        self.assertEqual(report["status"], "deduplicated")
        self.assertEqual(len(calls), 1)
        self.assertFalse((self.root / duplicate["source_path"]).exists())

    def test_failed_launch_retries_exactly_once_and_preserves_poke(self):
        outcomes = iter([
            {"status": "failed_launch", "blocked_reason": "no PID"},
            {"status": "failed_launch", "blocked_reason": "no activity"},
        ])
        consumer = ClaudeEventConsumer(self.root, processor=lambda **_: next(outcomes))
        report = consumer.process_once()
        self.assertEqual(report["status"], "failed_launch")
        self.assertEqual(report["attempt_count"], 2)
        self.assertTrue((self.root / self.poke["source_path"]).exists())
        self.assertIn("no activity", load_watcher_status(self.root)["last_blocker"])

    def test_running_requires_genuine_activity(self):
        consumer = ClaudeEventConsumer(self.root, processor=lambda **_: {
            "status": "completed", "pid": 88, "verdict": None
        })
        report = consumer.process_once()
        self.assertEqual(report["status"], "failed_launch")
        self.assertNotIn("review_running", report["transitions"])
        self.assertTrue((self.root / self.poke["source_path"]).exists())

    def test_buffered_output_valid_verdict_at_exit_is_not_failed_launch(self):
        consumer = ClaudeEventConsumer(self.root, processor=lambda **_: {
            "status": "completed", "pid": 89, "session_id": None,
            "verdict": "accepted", "assignment_status": "accepted",
        })
        report = consumer.process_once()
        self.assertEqual(report["status"], "resolved")
        self.assertEqual(report["verdict"], "accepted")
        self.assertFalse((self.root / self.poke["source_path"]).exists())

    def test_late_valid_verdict_is_recorded_even_after_timeout_classification(self):
        consumer = ClaudeEventConsumer(self.root, processor=lambda **_: {
            "status": "timed_out", "pid": 90, "session_id": None,
            "verdict": "changes_requested", "assignment_status": "changes_requested",
            "blocked_reason": "activity watchdog expired before final output",
        })
        report = consumer.process_once()
        self.assertEqual(report["status"], "resolved")
        self.assertEqual(report["verdict"], "changes_requested")
        self.assertFalse((self.root / self.poke["source_path"]).exists())

    def test_pending_over_five_minutes_surfaces_alert(self):
        path = self.root / self.poke["source_path"]
        data = json.loads(path.read_text(encoding="utf-8"))
        data["created_at"] = "2000-01-01T00:00:00Z"
        path.write_text(json.dumps(data), encoding="utf-8")
        consumer = ClaudeEventConsumer(self.root, processor=lambda **_: {
            "status": "failed_launch", "blocked_reason": "offline"
        })
        consumer.process_once()
        status = load_watcher_status(self.root)
        self.assertTrue(status["alert_active"])
        self.assertGreater(status["oldest_pending_poke_age_seconds"], 300)


if __name__ == "__main__":
    unittest.main()
