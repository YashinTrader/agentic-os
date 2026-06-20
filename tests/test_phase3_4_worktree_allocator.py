from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.worktree_allocator import (  # noqa: E402
    allocate_worktree,
    build_branch_name,
    build_worktree_path,
    cleanup_worktree,
    resolve_worktree_root,
    run_git,
    sanitize_task_id,
)


def _init_git_repo(path: Path) -> str:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


class WorktreeAllocatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir(parents=True)
        self.worktree_root = Path(self.tmp.name) / "worktrees"
        self.worktree_root.mkdir()
        os.environ["AGENTIC_OS_WORKTREE_ROOT"] = str(self.worktree_root)
        self.base_sha = _init_git_repo(self.repo)

    def tearDown(self) -> None:
        os.environ.pop("AGENTIC_OS_WORKTREE_ROOT", None)
        self.tmp.cleanup()

    def test_branch_name_sanitization(self) -> None:
        branch = build_branch_name("T-PHASE3-4", "run-abc123XYZ")
        self.assertEqual(branch, "agentic/t-phase3-4/run-abc123XY")
        self.assertRegex(branch, r"^agentic/[a-zA-Z0-9._/-]+$")

    def test_worktree_path_stays_inside_root(self) -> None:
        root = resolve_worktree_root(self.repo)
        path = build_worktree_path(root, "T-SAFE", "run-001")
        self.assertTrue(str(path).startswith(str(root.resolve())))

    def test_unsafe_task_id_rejected_for_containment(self) -> None:
        with self.assertRaises(ValueError):
            sanitize_task_id("../escape")

    def test_allocate_worktree_success(self) -> None:
        result = allocate_worktree(
            self.repo,
            task_id="T-ALLOC",
            run_id="run-alloc-001",
            base_sha=self.base_sha,
        )
        self.assertTrue(result.success, result.errors)
        self.assertIsNotNone(result.record)
        self.assertEqual(result.record.status, "allocated")
        self.assertTrue(Path(result.worktree_path).exists())
        self.assertTrue((self.repo / ".git").exists())

    def test_duplicate_active_allocation_blocked(self) -> None:
        first = allocate_worktree(
            self.repo,
            task_id="T-DUP",
            run_id="run-dup-001",
            base_sha=self.base_sha,
        )
        self.assertTrue(first.success, first.errors)

        second = allocate_worktree(
            self.repo,
            task_id="T-DUP-OTHER",
            run_id="run-dup-001",
            base_sha=self.base_sha,
        )
        self.assertFalse(second.success)
        self.assertTrue(any("run_id" in err for err in second.errors))

    def test_invalid_base_sha_blocked(self) -> None:
        bad_format = allocate_worktree(
            self.repo,
            task_id="T-BAD",
            run_id="run-bad-fmt",
            base_sha="not-a-sha",
        )
        self.assertFalse(bad_format.success)
        self.assertTrue(any("invalid base_sha" in err for err in bad_format.errors))

        missing = allocate_worktree(
            self.repo,
            task_id="T-BAD",
            run_id="run-bad-miss",
            base_sha="0000000000000000000000000000000000000000",
        )
        self.assertFalse(missing.success)
        self.assertTrue(any("base_sha not found" in err for err in missing.errors))

    def test_cleanup_refuses_dirty_worktree(self) -> None:
        allocated = allocate_worktree(
            self.repo,
            task_id="T-DRTY",
            run_id="run-dirty-001",
            base_sha=self.base_sha,
        )
        self.assertTrue(allocated.success, allocated.errors)
        assert allocated.record is not None

        dirty_file = Path(allocated.worktree_path) / "dirty-marker.txt"
        dirty_file.write_text("do not cleanup", encoding="utf-8")

        cleaned = cleanup_worktree(self.repo, allocated.record.allocation_id)
        self.assertFalse(cleaned.success)
        self.assertTrue(any("dirty" in err.lower() for err in cleaned.errors))
        self.assertTrue(dirty_file.exists())

    def test_run_git_never_uses_shell(self) -> None:
        with patch("dispatch.worktree_allocator.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["git", "rev-parse", "HEAD"],
                returncode=0,
                stdout=self.base_sha + "\n",
                stderr="",
            )
            code, out, err = run_git(self.repo, ["rev-parse", "HEAD"])
            self.assertEqual(code, 0)
            mock_run.assert_called_once()
            _args, kwargs = mock_run.call_args
            self.assertIs(kwargs.get("shell"), False)


if __name__ == "__main__":
    unittest.main()