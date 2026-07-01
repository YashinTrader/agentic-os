"""Phase 3.8 — file-based Composer assignment channel tests."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.assignment_channel import (  # noqa: E402
    ASSIGNMENT_SCHEMA_VERSION,
    generate_assignment_id,
    ingest_handoff_from_outbox,
    list_inbox_assignments,
    parse_assignment_record,
    parse_outbox_record,
    read_assignment,
    validate_inbox_payload,
    validate_outbox_payload,
    write_assignment,
)


class AssignmentChannelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_write_and_read_assignment(self) -> None:
        path, errors = write_assignment(
            self.root,
            task_id="T-COMPOSER-TEST",
            task_path="tasks/active/T-COMPOSER-TEST.yaml",
            base_sha="abc123",
            allowed_paths=["docs/**"],
        )
        self.assertEqual(errors, [])
        self.assertIsNotNone(path)
        record, read_errors = read_assignment(self.root, path.stem)
        self.assertEqual(read_errors, [])
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.task_id, "T-COMPOSER-TEST")
        self.assertEqual(record.status, "pending")
        self.assertEqual(record.adapter_id, "composer-restricted")

    def test_validate_inbox_rejects_missing_fields(self) -> None:
        errors = validate_inbox_payload({"schema_version": ASSIGNMENT_SCHEMA_VERSION})
        self.assertTrue(errors)

    def test_list_inbox_tolerates_malformed(self) -> None:
        inbox = self.root / "runtime" / "dispatch" / "assignments" / "inbox"
        inbox.mkdir(parents=True)
        (inbox / "bad.json").write_text("{not-json", encoding="utf-8")
        records, errors = list_inbox_assignments(self.root)
        self.assertEqual(len(records), 1)
        self.assertTrue(errors)

    def test_parse_outbox_record(self) -> None:
        payload = {
            "schema_version": ASSIGNMENT_SCHEMA_VERSION,
            "assignment_id": "assign-test",
            "task_id": "T-1",
            "adapter_id": "composer-restricted",
            "status": "completed",
            "finished_at": "2026-07-01T12:00:00Z",
            "handoff_path": "handoffs/T-1__composer__to__claude.md",
        }
        record = parse_outbox_record(payload)
        self.assertEqual(record.status, "completed")
        self.assertEqual(validate_outbox_payload(payload), [])

    def test_ingest_handoff_from_outbox(self) -> None:
        outbox = self.root / "runtime" / "dispatch" / "assignments" / "outbox"
        outbox.mkdir(parents=True)
        (outbox / "assign-1.json").write_text(
            json.dumps(
                {
                    "schema_version": ASSIGNMENT_SCHEMA_VERSION,
                    "assignment_id": "assign-1",
                    "task_id": "T-1",
                    "adapter_id": "composer-restricted",
                    "status": "completed",
                    "finished_at": "2026-07-01T12:00:00Z",
                    "handoff_path": "handoffs/T-1__composer__to__claude.md",
                }
            ),
            encoding="utf-8",
        )
        handoff, errors = ingest_handoff_from_outbox(self.root, "assign-1")
        self.assertEqual(errors, [])
        self.assertEqual(handoff, "handoffs/T-1__composer__to__claude.md")

    def test_generate_assignment_id_unique(self) -> None:
        a = generate_assignment_id("T-FOO")
        b = generate_assignment_id("T-FOO")
        self.assertNotEqual(a, b)
        self.assertIn("T-FOO", a)


class AssignmentParseTests(unittest.TestCase):
    def test_parse_assignment_record_wrong_adapter(self) -> None:
        payload = {
            "schema_version": ASSIGNMENT_SCHEMA_VERSION,
            "assignment_id": "a1",
            "task_id": "T",
            "adapter_id": "codex-restricted",
            "assigned_by": "claude",
            "assigned_to": "composer",
            "status": "pending",
            "created_at": "2026-07-01T12:00:00Z",
            "execution_route": "composer_local_builder",
            "task_path": "tasks/active/T.yaml",
            "handoff_rel": "handoffs/T__composer__to__claude.md",
        }
        record = parse_assignment_record(payload)
        self.assertTrue(record.parse_errors)


if __name__ == "__main__":
    unittest.main()