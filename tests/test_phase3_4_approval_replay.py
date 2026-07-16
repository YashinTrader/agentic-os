from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.approval_replay import (  # noqa: E402
    is_approval_consumed,
    try_claim_approval,
    validate_approval_id_for_claim,
)


class ApprovalReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _claim(self, approval_id: str = "approval-replay-001"):
        return try_claim_approval(
            self.root,
            approval_id=approval_id,
            run_id="run-replay-001",
            task_id="T-REPLAY",
            preview_hash="c" * 64,
            execution_request_id="exec-req-001",
        )

    def test_first_claim_succeeds(self) -> None:
        result = self._claim()
        self.assertTrue(result.claimed)
        self.assertFalse(result.already_consumed)
        self.assertTrue(is_approval_consumed(self.root, "approval-replay-001"))

    def test_double_claim_blocked(self) -> None:
        first = self._claim()
        self.assertTrue(first.claimed)

        second = self._claim()
        self.assertFalse(second.claimed)
        self.assertTrue(second.already_consumed)
        self.assertTrue(any("consumed" in err for err in second.errors))

    def test_concurrent_claim_only_one_wins(self) -> None:
        results: list = []
        barrier = threading.Barrier(8)

        def worker() -> None:
            barrier.wait()
            results.append(
                try_claim_approval(
                    self.root,
                    approval_id="approval-concurrent-001",
                    run_id="run-concurrent",
                    task_id="T-CONC",
                    preview_hash="d" * 64,
                    execution_request_id="exec-concurrent",
                )
            )

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        claimed = [r for r in results if r.claimed]
        replayed = [r for r in results if r.already_consumed]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(len(replayed), 7)

    def test_path_traversal_in_approval_id_blocked(self) -> None:
        for bad_id in ("../evil", "approval/bad", "approval\\bad", ".."):
            errors = validate_approval_id_for_claim(bad_id)
            self.assertTrue(errors, bad_id)

            result = try_claim_approval(
                self.root,
                approval_id=bad_id,
                run_id="run-bad",
                task_id="T-BAD",
                preview_hash="e" * 64,
                execution_request_id="exec-bad",
            )
            self.assertFalse(result.claimed)
            self.assertFalse(result.already_consumed)


if __name__ == "__main__":
    unittest.main()