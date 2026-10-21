from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dispatch.orchestrator_pokes import write_orchestrator_poke
from orchestrator.claude_event_consumer import (
    MAX_BACKOFF_SECONDS, ClaudeEventConsumer, backoff_seconds, load_watcher_status,
)
from orchestrator.rotating_log import RotatingLogWriter


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
        self.assertEqual(report["status"], "deferred")
        self.assertEqual(report["attempt_count"], 2)
        self.assertTrue((self.root / self.poke["source_path"]).exists())
        self.assertIn("no activity", load_watcher_status(self.root)["last_blocker"])

    def test_running_requires_genuine_activity(self):
        consumer = ClaudeEventConsumer(self.root, processor=lambda **_: {
            "status": "completed", "pid": 88, "verdict": None
        })
        report = consumer.process_once()
        self.assertEqual(report["status"], "deferred")
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

    def test_auth_deferral_becomes_eligible_only_after_probe_success(self):
        now = [datetime(2026, 10, 21, tzinfo=timezone.utc)]
        calls = []
        outcomes = iter([
            {"status": "failed_launch", "blocked_reason": "Claude authentication failed"},
            {"status": "failed_launch", "blocked_reason": "Claude authentication failed"},
            {"status": "completed", "pid": 7, "session_id": "s", "verdict": "accepted"},
        ])
        probe_results = iter([False, True])
        consumer = ClaudeEventConsumer(
            self.root, processor=lambda **_: calls.append(1) or next(outcomes),
            condition_probe=lambda _: next(probe_results), now=lambda: now[0],
        )
        first = consumer.process_once()
        self.assertEqual(first["blocked_on"], "auth:claude")
        now[0] += timedelta(minutes=1)
        self.assertEqual(consumer.process_once()["status"], "deferred")
        self.assertEqual(len(calls), 2)
        now[0] += timedelta(minutes=10)
        self.assertEqual(consumer.process_once()["status"], "resolved")
        self.assertEqual(len(calls), 3)

    def test_unchanged_failure_is_not_relaunched_before_backoff(self):
        now = [datetime(2026, 10, 21, tzinfo=timezone.utc)]
        calls = []
        consumer = ClaudeEventConsumer(
            self.root,
            processor=lambda **_: calls.append(1) or {"status": "failed_launch", "blocked_reason": "deterministic parse error"},
            condition_probe=lambda _: False, now=lambda: now[0],
        )
        consumer.process_once()
        now[0] += timedelta(minutes=4, seconds=59)
        self.assertEqual(consumer.process_once()["status"], "deferred")
        self.assertEqual(len(calls), 2)  # launch watchdog retries exactly once, then defers

    def test_backoff_grows_and_caps_at_six_hours(self):
        self.assertEqual(backoff_seconds(1), 300)
        self.assertEqual(backoff_seconds(2), 600)
        self.assertEqual(backoff_seconds(99), MAX_BACKOFF_SECONDS)

    def test_escalation_after_six_hours_includes_blocked_reason(self):
        now = [datetime(2026, 10, 21, tzinfo=timezone.utc)]
        consumer = ClaudeEventConsumer(
            self.root, processor=lambda **_: {"status": "failed_launch", "blocked_reason": "authentication expired"},
            condition_probe=lambda _: False, now=lambda: now[0],
        )
        consumer.process_once()
        now[0] += timedelta(hours=6, seconds=1)
        consumer.process_once()
        status = load_watcher_status(self.root)
        self.assertTrue(status["alert_active"])
        self.assertTrue(status["deferred_escalation_active"])
        self.assertEqual(status["deferred_blocked_on"], ["auth:claude"])

    def test_idle_ticks_do_not_log_and_state_change_logs_once(self):
        source = self.root / self.poke["source_path"]
        source.unlink()
        events = []
        consumer = ClaudeEventConsumer(self.root, state_logger=events.append)
        consumer.process_once()
        consumer.process_once()
        self.assertEqual(events, [])
        status = load_watcher_status(self.root)
        self.assertEqual(status["idle_ticks"], 2)

        write_orchestrator_poke(
            self.root, source="composer", assignment_id="assign-2", task_id="T-2", event="assignment_completed"
        )
        consumer = ClaudeEventConsumer(
            self.root, processor=lambda **_: {"status": "completed", "pid": 1, "session_id": "s", "verdict": "accepted"},
            state_logger=events.append,
        )
        consumer.process_once()
        self.assertEqual([event["event"] for event in events], ["claimed"])

    def test_rotation_triggers_at_size_cap(self):
        path = self.root / "logs" / "supervisor.jsonl"
        writer = RotatingLogWriter(path, max_bytes=10, backups=2)
        writer.write("123456789\n")
        writer.write("abc\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "abc\n")
        self.assertEqual(path.with_name("supervisor.jsonl.1").read_text(encoding="utf-8"), "123456789\n")


if __name__ == "__main__":
    unittest.main()
