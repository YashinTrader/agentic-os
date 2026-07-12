"""Phase 3.8 / 3.8B — file-based Composer/Grok assignment channel tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.assignment_channel import (  # noqa: E402
    ASSIGNMENT_SCHEMA_VERSION,
    claim_assignment,
    complete_assignment,
    create_assignment_from_task_yaml,
    evaluate_assignment_pickability,
    generate_assignment_id,
    ingest_handoff_from_outbox,
    ingest_outbox_results,
    list_inbox_assignments,
    list_pending_assignments,
    parse_assignment_record,
    parse_outbox_record,
    read_assignment,
    validate_assignment_payload,
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
            title="Composer test",
            goal="Validate channel",
            base_branch="main",
            base_sha="abc123",
            new_branch="agent/composer/T-COMPOSER-TEST",
            allowed_paths=["docs/**"],
            acceptance_criteria=["tests pass"],
            verification_commands=["python scripts/validate.py"],
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
        self.assertEqual(record.title, "Composer test")
        self.assertEqual(record.base_sha, "abc123")
        self.assertIn("docs/**", record.allowed_paths)

    def test_validate_inbox_rejects_missing_fields(self) -> None:
        errors = validate_inbox_payload({"schema_version": ASSIGNMENT_SCHEMA_VERSION})
        self.assertTrue(errors)

    def test_validate_full_contract_requires_all_fields(self) -> None:
        errors = validate_assignment_payload(
            {
                "schema_version": ASSIGNMENT_SCHEMA_VERSION,
                "assignment_id": "a1",
                "task_id": "T",
            }
        )
        self.assertTrue(any("missing required fields" in e for e in errors))

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
            "title": "t",
            "goal": "g",
            "base_branch": "main",
            "base_sha": "abc",
            "new_branch": "agent/composer/T",
            "allowed_paths": [],
            "forbidden_operations": [],
            "acceptance_criteria": [],
            "verification_commands": [],
            "timeout": 60,
            "handoff_path": "handoffs/T__composer__to__claude.md",
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


class AssignmentClaimLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir(parents=True)
        tasks = self.root / "tasks" / "active"
        tasks.mkdir(parents=True)
        self.task_id = "T-CLAIM-LOOP"
        task = {
            "id": self.task_id,
            "title": "Claim loop fixture",
            "status": "ready",
            "owner": "composer",
            "reviewer": "claude",
            "goals": ["Prove claim lifecycle"],
            "acceptance": ["Claimed once only"],
            "outputs": ["docs/EXAMPLE.md"],
            "notes": "fixture",
        }
        (tasks / f"{self.task_id}.yaml").write_text(
            yaml.safe_dump(task, sort_keys=False), encoding="utf-8"
        )
        path, errors = write_assignment(
            self.root,
            task_id=self.task_id,
            title="Claim loop fixture",
            goal="Prove claim lifecycle",
            base_branch="main",
            base_sha="deadbeef" * 5,
            new_branch=f"agent/composer/{self.task_id}",
            allowed_paths=["docs/**"],
            acceptance_criteria=["Claimed once only"],
            verification_commands=["python scripts/validate.py"],
            task_path=f"tasks/active/{self.task_id}.yaml",
            assignment_id="assign-claim-loop-1",
        )
        self.assertEqual(errors, [])
        self.assertIsNotNone(path)
        self.assignment_id = "assign-claim-loop-1"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_claim_is_atomic_and_not_re_pickable(self) -> None:
        record, errors = claim_assignment(self.root, self.assignment_id)
        self.assertEqual(errors, [])
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.status, "claimed")
        claim_path = (
            self.root
            / "runtime"
            / "dispatch"
            / "assignments"
            / "claims"
            / f"{self.assignment_id}.json"
        )
        self.assertTrue(claim_path.is_file())

        # Re-claim must fail
        again, again_errors = claim_assignment(self.root, self.assignment_id)
        self.assertIsNone(again)
        self.assertTrue(again_errors)

        # Not in pending list
        pending, _ = list_pending_assignments(self.root)
        self.assertEqual(pending, [])

        # Pickability evaluator
        refreshed, _ = read_assignment(self.root, self.assignment_id)
        assert refreshed is not None
        ok, reason = evaluate_assignment_pickability(self.root, refreshed)
        self.assertFalse(ok)
        self.assertTrue("claimed" in reason or "claim" in reason.lower())

    def test_task_yaml_syncs_on_claim_and_complete(self) -> None:
        claim_assignment(self.root, self.assignment_id)
        task_path = self.root / "tasks" / "active" / f"{self.task_id}.yaml"
        task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
        self.assertEqual(task["status"], "in_progress")

        out, errors = complete_assignment(
            self.root,
            self.assignment_id,
            handoff_path=f"handoffs/{self.task_id}__composer__to__claude.md",
            branch_tip_sha="a" * 40,
            branch_name=f"agent/composer/{self.task_id}",
            result_summary="done",
        )
        self.assertEqual([e for e in errors if "not found" not in e], [])
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out.status, "awaiting_review")

        task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
        self.assertEqual(task["status"], "review")

        # Completed assignment never re-picked
        pending, _ = list_pending_assignments(self.root)
        self.assertEqual(pending, [])
        second, second_errors = claim_assignment(self.root, self.assignment_id)
        self.assertIsNone(second)
        self.assertTrue(second_errors)

    def test_completed_with_outbox_is_not_pickable(self) -> None:
        claim_assignment(self.root, self.assignment_id)
        complete_assignment(
            self.root,
            self.assignment_id,
            handoff_path=f"handoffs/{self.task_id}__composer__to__claude.md",
            branch_tip_sha="b" * 40,
        )
        records, _ = list_inbox_assignments(self.root)
        self.assertEqual(len(records), 1)
        ok, reason = evaluate_assignment_pickability(self.root, records[0])
        self.assertFalse(ok)
        self.assertTrue(reason)

    def test_ingest_outbox_results(self) -> None:
        claim_assignment(self.root, self.assignment_id)
        complete_assignment(
            self.root,
            self.assignment_id,
            handoff_path=f"handoffs/{self.task_id}__composer__to__claude.md",
            branch_tip_sha="c" * 40,
            branch_name=f"agent/composer/{self.task_id}",
            result_summary="dogfood",
        )
        results, errors = ingest_outbox_results(self.root)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["assignment_id"], self.assignment_id)
        ingest_path = (
            self.root
            / "runtime"
            / "dispatch"
            / "assignments"
            / "ingest"
            / "latest_ingest.json"
        )
        self.assertTrue(ingest_path.is_file())

    def test_create_from_task_yaml(self) -> None:
        path, errors = create_assignment_from_task_yaml(
            self.root,
            f"tasks/active/{self.task_id}.yaml",
            base_sha="d" * 40,
        )
        # Already have one assignment; this creates another
        self.assertEqual(errors, [])
        self.assertIsNotNone(path)


class AssignmentCliImportTests(unittest.TestCase):
    def test_assignments_cli_module_imports(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "assignments_cli",
            REPO_ROOT / "scripts" / "assignments.py",
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertTrue(hasattr(mod, "main"))
        self.assertTrue(hasattr(mod, "cmd_claim"))


if __name__ == "__main__":
    unittest.main()
