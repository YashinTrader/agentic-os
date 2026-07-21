"""Tests for genuine Claude activity detection (buffered stdout safe)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.activity_detect import (
    detect_activity_from_paths,
    detect_activity_signals,
    is_valid_structured_review_result,
    merge_activity_with_exit_result,
)


def _valid_payload() -> dict:
    return {
        "verdict": "accepted",
        "summary": "ok",
        "repository_integrity": {
            "verified": True,
            "branch": "agent/x",
            "local_sha": "a" * 40,
            "remote_sha": "a" * 40,
        },
        "tests": [{"command": "python scripts/validate.py", "exit_code": 0, "result": "ok"}],
        "findings": [],
        "required_changes": [],
        "next_assignment": {
            "required": False,
            "task_id": None,
            "goal": None,
            "assigned_to": None,
        },
    }


class ActivityDetectTests(unittest.TestCase):
    def test_session_id_is_activity(self):
        sig = detect_activity_signals('{"session_id":"abc-123","type":"assistant"}')
        self.assertTrue(sig["genuine_activity"])
        self.assertEqual(sig["session_id"], "abc-123")

    def test_valid_structured_result_is_activity(self):
        envelope = {"type": "result", "result": json.dumps(_valid_payload()), "session_id": "s1"}
        text = json.dumps(envelope)
        self.assertTrue(is_valid_structured_review_result(text))
        merged = merge_activity_with_exit_result(
            mid_run_activity=False,
            exit_code=0,
            stdout=text,
        )
        self.assertTrue(merged["genuine_activity"])
        self.assertTrue(merged["valid_structured_result"])
        self.assertFalse(merged["mid_run_activity"])

    def test_buffered_mid_run_miss_recovered_at_exit(self):
        """Mid-run saw nothing (buffering); exit payload still counts."""
        payload = json.dumps({"type": "result", "result": json.dumps(_valid_payload())})
        merged = merge_activity_with_exit_result(
            mid_run_activity=False,
            exit_code=0,
            stdout=payload,
        )
        self.assertTrue(merged["genuine_activity"])

    def test_empty_output_is_not_activity(self):
        sig = detect_activity_signals("")
        self.assertFalse(sig["genuine_activity"])
        merged = merge_activity_with_exit_result(
            mid_run_activity=False,
            exit_code=1,
            stdout="",
            stderr="boom",
        )
        self.assertFalse(merged["genuine_activity"])

    def test_incremental_file_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stdout.log"
            path.write_text('{"type":"assistant","session_id":"from-file"}\n', encoding="utf-8")
            sig = detect_activity_from_paths(path)
            self.assertTrue(sig["genuine_activity"])
            self.assertEqual(sig["session_id"], "from-file")


if __name__ == "__main__":
    unittest.main()
