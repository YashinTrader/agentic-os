from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.runtime_capture import (  # noqa: E402
    ExecutionResult,
    append_run_event,
    run_directory,
    write_execution_request,
    write_handoff_required_md,
    write_result,
    write_rollback_md,
)


class RuntimeCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_run_directory_and_artifacts(self) -> None:
        run_id = "dispatch-20260612T120000Z-cap0001"
        run_dir = run_directory(self.root, run_id)
        write_execution_request(run_dir, {"run_id": run_id, "dry_run": True})
        result = ExecutionResult(
            run_id=run_id,
            task_id="T-CAP",
            adapter_id="local-python-exec-test",
            executed=False,
            execution_allowed=True,
            approval_level="none",
            approval_status="none",
            handoff_path="handoffs/T-CAP.md",
            rollback_path=f"runtime/dispatch/runs/{run_id}/rollback.md",
        )
        write_result(run_dir, result)
        write_rollback_md(run_dir, "rollback notes")
        write_handoff_required_md(run_dir, "handoffs/T-CAP.md")
        append_run_event(run_dir, {"type": "dispatch_requested"})

        self.assertTrue((run_dir / "execution_request.json").exists())
        self.assertTrue((run_dir / "result.json").exists())
        self.assertTrue((run_dir / "events.jsonl").exists())
        self.assertTrue((run_dir / "rollback.md").exists())
        self.assertTrue((run_dir / "handoff_required.md").exists())

        loaded = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertFalse(loaded["executed"])
        self.assertEqual(loaded["handoff_path"], "handoffs/T-CAP.md")


if __name__ == "__main__":
    unittest.main()