from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.worktree_registry import (  # noqa: E402
    ACTIVE_STATUSES,
    AllocationRecord,
    assert_no_active_duplicate,
    find_by_run_id,
    find_by_worktree_path,
    load_allocation_record,
    new_allocation_id,
    save_allocation_record,
    transition_status,
    utc_now,
)


def _sample_record(
    *,
    allocation_id: str | None = None,
    run_id: str = "run-reg-001",
    status: str = "allocated",
    worktree_path: str = "/tmp/wt/run-reg-001",
    branch_name: str = "agentic/t-reg/run-reg-001",
) -> AllocationRecord:
    now = utc_now()
    expires = (
        datetime.now(timezone.utc) + timedelta(hours=24)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    alloc_id = allocation_id or new_allocation_id()
    return AllocationRecord(
        allocation_id=alloc_id,
        run_id=run_id,
        task_id="T-REG",
        repo_root="/repo",
        worktree_root="/repo-worktrees",
        worktree_path=worktree_path,
        branch_name=branch_name,
        base_sha="abc1234",
        base_branch="main",
        created_at=now,
        expires_at=expires,
        status=status,
        cleanup_policy="manual",
        writes_files=True,
        owner="operator",
        last_verified_at=now,
        dirty=False,
        git_head="abc1234",
        error="",
        audit=[],
    )


class WorktreeRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_save_and_lookup_by_run_id(self) -> None:
        record = _sample_record()
        record.repo_root = str(self.root)
        record.worktree_root = str(self.root / "worktrees")
        save_allocation_record(self.root, record)

        loaded = load_allocation_record(self.root, record.allocation_id)
        self.assertEqual(loaded.run_id, record.run_id)
        self.assertEqual(loaded.status, "allocated")

        found = find_by_run_id(self.root, record.run_id)
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.allocation_id, record.allocation_id)

    def test_lookup_by_worktree_path(self) -> None:
        record = _sample_record(worktree_path=str(self.root / "wt" / "path-a"))
        record.repo_root = str(self.root)
        record.worktree_root = str(self.root / "worktrees")
        save_allocation_record(self.root, record)

        found = find_by_worktree_path(self.root, str(self.root / "wt" / "path-a"))
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.allocation_id, record.allocation_id)

    def test_status_transitions_persist(self) -> None:
        record = _sample_record()
        record.repo_root = str(self.root)
        record.worktree_root = str(self.root / "worktrees")
        save_allocation_record(self.root, record)

        active = transition_status(self.root, record.allocation_id, "active")
        self.assertEqual(active.status, "active")
        self.assertTrue(active.audit)

        completed = transition_status(self.root, record.allocation_id, "completed")
        self.assertEqual(completed.status, "completed")

        reloaded = load_allocation_record(self.root, record.allocation_id)
        self.assertEqual(reloaded.status, "completed")

    def test_duplicate_active_ownership_detected(self) -> None:
        first = _sample_record(run_id="run-own-001", branch_name="agentic/t-own/b1")
        first.repo_root = str(self.root)
        first.worktree_root = str(self.root / "worktrees")
        first.worktree_path = str(self.root / "wt" / "b1")
        save_allocation_record(self.root, first)

        reasons = assert_no_active_duplicate(
            self.root,
            run_id="run-own-001",
            branch_name="agentic/t-own/b2",
            worktree_path=str(self.root / "wt" / "b2"),
        )
        self.assertTrue(any("run_id" in r for r in reasons))

        reasons_branch = assert_no_active_duplicate(
            self.root,
            run_id="run-own-002",
            branch_name="agentic/t-own/b1",
            worktree_path=str(self.root / "wt" / "b3"),
        )
        self.assertTrue(any("branch" in r for r in reasons_branch))

        reasons_path = assert_no_active_duplicate(
            self.root,
            run_id="run-own-003",
            branch_name="agentic/t-own/b3",
            worktree_path=str(self.root / "wt" / "b1"),
        )
        self.assertTrue(any("worktree path" in r for r in reasons_path))

    def test_inactive_status_not_counted_as_active_duplicate(self) -> None:
        cleaned = _sample_record(run_id="run-cleaned", status="cleaned")
        cleaned.repo_root = str(self.root)
        cleaned.worktree_root = str(self.root / "worktrees")
        cleaned.worktree_path = str(self.root / "wt" / "cleaned")
        save_allocation_record(self.root, cleaned)

        reasons = assert_no_active_duplicate(
            self.root,
            run_id="run-cleaned",
            branch_name="agentic/t-own/new",
            worktree_path=str(self.root / "wt" / "new"),
        )
        self.assertEqual(reasons, [])
        self.assertNotIn("cleaned", ACTIVE_STATUSES)


if __name__ == "__main__":
    unittest.main()