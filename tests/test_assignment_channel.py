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
    accept_assignment,
    claim_assignment,
    complete_assignment,
    create_assignment_from_task_yaml,
    evaluate_assignment_pickability,
    generate_assignment_id,
    ingest_handoff_from_outbox,
    ingest_outbox_results,
    list_inbox_assignments,
    list_assignment_events,
    list_pending_assignments,
    parse_assignment_record,
    parse_outbox_record,
    poke_assignment,
    read_assignment,
    reject_assignment,
    request_changes_assignment,
    resolve_assignment,
    reassign_assignment,
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


class AssignmentFallbackRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir(parents=True)
        path, errors = write_assignment(
            self.root,
            task_id="T-FALLBACK",
            title="Fallback routing",
            goal="Move unavailable Grok work to Codex",
            base_branch="main",
            base_sha="a" * 40,
            allowed_paths=["docs/**"],
            acceptance_criteria=["Codex can claim the replacement"],
            verification_commands=["python scripts/validate.py"],
            assigned_by="claude",
            assigned_to="grok",
            assignment_id="assign-primary",
        )
        self.assertEqual(errors, [])
        self.assertIsNotNone(path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_reassigns_unavailable_grok_to_codex_and_pokes_target(self) -> None:
        replacement, errors = reassign_assignment(
            self.root,
            "assign-primary",
            reassigned_by="claude",
            assigned_to="codex",
            reason="quota_exhausted",
            poke=True,
            sync_task_yaml=False,
        )
        self.assertEqual(errors, [])
        self.assertIsNotNone(replacement)
        assert replacement is not None
        self.assertEqual(replacement.status, "pending")
        self.assertEqual(replacement.assigned_to, "codex")
        self.assertEqual(replacement.adapter_id, "codex-restricted")
        self.assertEqual(replacement.execution_route, "codex_local_builder")
        self.assertEqual(replacement.reassigned_from, "assign-primary")
        self.assertIn("agent/codex/", replacement.new_branch)

        original, original_errors = read_assignment(self.root, "assign-primary")
        self.assertEqual(original_errors, [])
        assert original is not None
        self.assertEqual(original.status, "superseded")
        self.assertEqual(original.reassigned_to_assignment_id, replacement.assignment_id)

        events, event_errors = list_assignment_events(self.root)
        self.assertEqual(event_errors, [])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "assignment.reassigned")
        self.assertEqual(events[0]["source"], "claude")
        self.assertEqual(events[0]["target"], "codex")
        self.assertEqual(events[0]["wake_state"], "notification_queued")

    def test_only_original_orchestrator_can_reassign(self) -> None:
        replacement, errors = reassign_assignment(
            self.root,
            "assign-primary",
            reassigned_by="composer",
            assigned_to="codex",
            reason="unavailable",
            sync_task_yaml=False,
        )
        self.assertIsNone(replacement)
        self.assertTrue(any("orchestrator" in error for error in errors))
        pending, _ = list_pending_assignments(self.root)
        self.assertEqual([record.assignment_id for record in pending], ["assign-primary"])

    def test_builder_identity_cannot_create_assignments(self) -> None:
        path, errors = write_assignment(
            self.root,
            task_id="T-BUILDER-ASSIGN",
            assigned_by="codex",
            assigned_to="composer",
        )
        self.assertIsNone(path)
        self.assertTrue(any("may not create assignments" in error for error in errors))

    def test_builder_cannot_claim_assignment_for_another_builder(self) -> None:
        record, errors = claim_assignment(
            self.root,
            "assign-primary",
            claimed_by="codex",
        )
        self.assertIsNone(record)
        self.assertTrue(any("assigned to" in error for error in errors))

    def test_builder_cannot_poke_another_builder(self) -> None:
        event, errors = poke_assignment(
            self.root,
            "assign-primary",
            actor="codex",
            message="pick this up",
        )
        self.assertIsNone(event)
        self.assertTrue(any("orchestrator" in error for error in errors))

    def test_superseded_assignment_cannot_be_reassigned_twice(self) -> None:
        first, first_errors = reassign_assignment(
            self.root,
            "assign-primary",
            reassigned_by="claude",
            assigned_to="codex",
            reason="unavailable",
            sync_task_yaml=False,
        )
        self.assertEqual(first_errors, [])
        self.assertIsNotNone(first)
        second, second_errors = reassign_assignment(
            self.root,
            "assign-primary",
            reassigned_by="claude",
            assigned_to="codex",
            reason="unavailable",
        )
        self.assertIsNone(second)
        self.assertTrue(second_errors)

    def test_fallback_completion_preserves_codex_adapter_identity(self) -> None:
        replacement, errors = reassign_assignment(
            self.root,
            "assign-primary",
            reassigned_by="claude",
            assigned_to="codex",
            reason="timeout",
            sync_task_yaml=False,
        )
        self.assertEqual(errors, [])
        assert replacement is not None
        claimed, claim_errors = claim_assignment(
            self.root,
            replacement.assignment_id,
            claimed_by="codex",
            sync_task_yaml=False,
        )
        self.assertEqual(claim_errors, [])
        self.assertIsNotNone(claimed)
        outbox, complete_errors = complete_assignment(
            self.root,
            replacement.assignment_id,
            branch_tip_sha="b" * 40,
            sync_task_yaml=False,
        )
        self.assertEqual(complete_errors, [])
        assert outbox is not None
        self.assertEqual(outbox.adapter_id, "codex-restricted")


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
        self.assertTrue(hasattr(mod, "cmd_resolve"))


class AssignmentReviewerResolutionTests(unittest.TestCase):
    """Phase 3.8B reviewer verbs: accept / request-changes / reject."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir(parents=True)
        tasks = self.root / "tasks" / "active"
        tasks.mkdir(parents=True)
        self.task_id = "T-REVIEW-VERBS"
        task = {
            "id": self.task_id,
            "title": "Reviewer verbs fixture",
            "status": "ready",
            "owner": "composer",
            "reviewer": "claude",
            "goals": ["Prove resolution verbs"],
            "acceptance": ["accept/request-changes/reject work"],
            "outputs": ["docs/EXAMPLE.md"],
        }
        (tasks / f"{self.task_id}.yaml").write_text(
            yaml.safe_dump(task, sort_keys=False), encoding="utf-8"
        )
        path, errors = write_assignment(
            self.root,
            task_id=self.task_id,
            title="Reviewer verbs fixture",
            goal="Prove resolution verbs",
            base_branch="main",
            base_sha="c" * 40,
            new_branch=f"agent/composer/{self.task_id}",
            acceptance_criteria=["accept/request-changes/reject work"],
            verification_commands=["python scripts/validate.py"],
            task_path=f"tasks/active/{self.task_id}.yaml",
            assignment_id="assign-review-verbs-1",
        )
        self.assertEqual(errors, [])
        self.assertIsNotNone(path)
        self.assignment_id = "assign-review-verbs-1"
        claim_assignment(self.root, self.assignment_id)
        complete_assignment(
            self.root,
            self.assignment_id,
            handoff_path=f"handoffs/{self.task_id}__composer__to__claude.md",
            branch_tip_sha="d" * 40,
            result_summary="ready for review",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_accept_marks_accepted_and_syncs_task_done(self) -> None:
        record, errors = accept_assignment(
            self.root,
            self.assignment_id,
            note="LGTM",
            reviewed_by="claude",
        )
        self.assertEqual([e for e in errors if "not found" not in e], [])
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.status, "accepted")
        self.assertEqual(record.reviewed_by, "claude")
        self.assertEqual(record.resolution_note, "LGTM")
        self.assertIsNotNone(record.reviewed_at)

        # Terminal: not re-claimable
        pending, _ = list_pending_assignments(self.root)
        self.assertEqual(pending, [])
        again, again_errors = claim_assignment(self.root, self.assignment_id)
        self.assertIsNone(again)
        self.assertTrue(again_errors)

        # Outbox carries resolution
        outbox_path = (
            self.root
            / "runtime"
            / "dispatch"
            / "assignments"
            / "outbox"
            / f"{self.assignment_id}.json"
        )
        out = json.loads(outbox_path.read_text(encoding="utf-8"))
        self.assertEqual(out["status"], "accepted")
        self.assertEqual(out["reviewed_by"], "claude")
        self.assertEqual(out["resolution_note"], "LGTM")

        # Task YAML -> done
        done_path = self.root / "tasks" / "done" / f"{self.task_id}.yaml"
        self.assertTrue(done_path.is_file())
        task = yaml.safe_load(done_path.read_text(encoding="utf-8"))
        self.assertEqual(task["status"], "done")

        # Ingest surfaces resolution
        results, _ = ingest_outbox_results(self.root)
        self.assertEqual(results[0]["outbox_status"], "accepted")
        self.assertEqual(results[0]["assignment_status"], "accepted")
        self.assertEqual(results[0]["reviewed_by"], "claude")

    def test_reject_requires_note_and_blocks_task(self) -> None:
        missing, missing_errors = reject_assignment(
            self.root, self.assignment_id, note="", reviewed_by="claude"
        )
        self.assertIsNone(missing)
        self.assertTrue(any("requires" in e for e in missing_errors))

        record, errors = reject_assignment(
            self.root,
            self.assignment_id,
            note="Fails acceptance: missing tests",
            reviewed_by="claude",
        )
        self.assertEqual([e for e in errors if "not found" not in e], [])
        assert record is not None
        self.assertEqual(record.status, "rejected")
        self.assertEqual(record.resolution_note, "Fails acceptance: missing tests")

        pending, _ = list_pending_assignments(self.root)
        self.assertEqual(pending, [])

        blocked = self.root / "tasks" / "blocked" / f"{self.task_id}.yaml"
        self.assertTrue(blocked.is_file())
        task = yaml.safe_load(blocked.read_text(encoding="utf-8"))
        self.assertEqual(task["status"], "blocked")

    def test_request_changes_reclaimable_once_per_cycle(self) -> None:
        record, errors = request_changes_assignment(
            self.root,
            self.assignment_id,
            note="Please add invalid-transition tests",
            reviewed_by="claude",
        )
        self.assertEqual([e for e in errors if "not found" not in e], [])
        assert record is not None
        self.assertEqual(record.status, "changes_requested")
        self.assertEqual(
            record.correction_note, "Please add invalid-transition tests"
        )

        # Re-claimable for correction cycle
        pending, _ = list_pending_assignments(self.root)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].assignment_id, self.assignment_id)

        reclaimed, reclaim_errors = claim_assignment(self.root, self.assignment_id)
        self.assertEqual(reclaim_errors, [])
        assert reclaimed is not None
        self.assertEqual(reclaimed.status, "claimed")
        # Correction note preserved for the builder
        self.assertEqual(
            reclaimed.correction_note, "Please add invalid-transition tests"
        )

        # Exactly once: cannot re-claim while claimed
        again, again_errors = claim_assignment(self.root, self.assignment_id)
        self.assertIsNone(again)
        self.assertTrue(again_errors)

        # After re-complete, can request-changes again (new cycle)
        complete_assignment(
            self.root,
            self.assignment_id,
            handoff_path=f"handoffs/{self.task_id}__composer__to__claude.md",
            branch_tip_sha="e" * 40,
            result_summary="fixed",
        )
        second, second_errors = request_changes_assignment(
            self.root,
            self.assignment_id,
            note="Still missing one edge case",
            reviewed_by="claude",
        )
        self.assertEqual([e for e in second_errors if "not found" not in e], [])
        assert second is not None
        self.assertEqual(second.status, "changes_requested")
        self.assertEqual(second.correction_note, "Still missing one edge case")

        # Task YAML back to ready on changes_requested
        ready = self.root / "tasks" / "active" / f"{self.task_id}.yaml"
        task = yaml.safe_load(ready.read_text(encoding="utf-8"))
        self.assertEqual(task["status"], "ready")

    def test_invalid_transition_from_pending_rejected(self) -> None:
        path, _ = write_assignment(
            self.root,
            task_id="T-OTHER",
            title="Other",
            goal="g",
            assignment_id="assign-pending-only",
        )
        self.assertIsNotNone(path)
        record, errors = accept_assignment(
            self.root, "assign-pending-only", reviewed_by="claude"
        )
        self.assertIsNone(record)
        self.assertTrue(any("awaiting_review" in e for e in errors))

        record2, errors2 = resolve_assignment(
            self.root,
            self.assignment_id,
            resolution="accepted",
            reviewed_by="claude",
        )
        # First assignment is still awaiting_review from setUp — accept works.
        # Force invalid by accepting twice:
        self.assertIsNotNone(record2)
        record3, errors3 = accept_assignment(
            self.root, self.assignment_id, reviewed_by="claude"
        )
        self.assertIsNone(record3)
        self.assertTrue(any("awaiting_review" in e for e in errors3))

    def test_request_changes_requires_note(self) -> None:
        record, errors = request_changes_assignment(
            self.root, self.assignment_id, note="   ", reviewed_by="claude"
        )
        self.assertIsNone(record)
        self.assertTrue(any("requires" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
