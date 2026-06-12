from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.worktree_policy import evaluate_worktree_policy  # noqa: E402


class WorktreePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir(parents=True)
        (self.root / "tasks").mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_cwd_inside_repo_allowed(self) -> None:
        result = evaluate_worktree_policy(
            self.root,
            cwd=str(self.root),
            scope_paths=["tasks/"],
            writes_files=False,
            worktree_required=False,
        )
        self.assertTrue(result.allowed)

    def test_cwd_outside_repo_blocked(self) -> None:
        result = evaluate_worktree_policy(
            self.root,
            cwd="/tmp/outside",
            scope_paths=[],
            writes_files=False,
            worktree_required=False,
        )
        self.assertFalse(result.allowed)
        self.assertTrue(any("outside" in r.lower() or "escapes" in r.lower() for r in result.blocked_reasons))

    def test_writes_files_without_worktree_blocked(self) -> None:
        result = evaluate_worktree_policy(
            self.root,
            cwd=str(self.root),
            scope_paths=[],
            writes_files=True,
            worktree_required=True,
            worktree_root=None,
        )
        self.assertFalse(result.allowed)
        self.assertTrue(any("worktree" in r for r in result.blocked_reasons))

    def test_scope_path_traversal_blocked(self) -> None:
        result = evaluate_worktree_policy(
            self.root,
            cwd=str(self.root),
            scope_paths=["../outside"],
            writes_files=False,
            worktree_required=False,
        )
        self.assertFalse(result.allowed)


if __name__ == "__main__":
    unittest.main()