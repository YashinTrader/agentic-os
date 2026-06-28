from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.agent_result_parser import parse_agent_execution_result  # noqa: E402


class CodexResultParserTests(unittest.TestCase):
    def test_exit_zero_without_handoff_is_not_verified(self) -> None:
        result = parse_agent_execution_result(
            run_id="r1",
            task_id="T1",
            adapter_id="codex-restricted",
            process_exit_code=0,
            timed_out=False,
            started_at="2026-06-22T12:00:00Z",
            finished_at="2026-06-22T12:01:00Z",
            stdout_path="out.txt",
            stderr_path="err.txt",
            agent_output_path="agent.txt",
            handoff_path="missing.md",
        )
        self.assertEqual(result.completion_status, "handoff_missing")

    def test_completed_verified_requires_verification_and_diff(self) -> None:
        handoff = REPO_ROOT / "runtime" / "dispatch" / "test_handoff.md"
        handoff.parent.mkdir(parents=True, exist_ok=True)
        handoff.write_text("# handoff\n", encoding="utf-8")
        try:
            result = parse_agent_execution_result(
                run_id="r2",
                task_id="T2",
                adapter_id="codex-restricted",
                process_exit_code=0,
                timed_out=False,
                started_at="2026-06-22T12:00:00Z",
                finished_at="2026-06-22T12:05:00Z",
                stdout_path="out.txt",
                stderr_path="err.txt",
                agent_output_path="agent.txt",
                handoff_path=str(handoff),
                git_diff_stat="1 file changed",
                files_changed=["foo.py"],
                verification_commands=["python scripts/validate.py"],
                verification_results=[{"command": "python scripts/validate.py", "exit_code": 0}],
            )
            self.assertEqual(result.completion_status, "completed_verified")
        finally:
            handoff.unlink(missing_ok=True)

    def test_blocked_reasons_force_blocked_status(self) -> None:
        result = parse_agent_execution_result(
            run_id="r3",
            task_id="T3",
            adapter_id="codex-restricted",
            process_exit_code=0,
            timed_out=False,
            started_at="2026-06-22T12:00:00Z",
            finished_at="2026-06-22T12:01:00Z",
            stdout_path="o",
            stderr_path="e",
            agent_output_path="a",
            blocked_reasons=["preview stale"],
        )
        self.assertEqual(result.completion_status, "blocked")


if __name__ == "__main__":
    unittest.main()