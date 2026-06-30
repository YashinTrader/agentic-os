from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class CanaryRefusalTests(unittest.TestCase):
    def test_dry_run_refuses_live_execution(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "run_codex_canary.py"),
                "--dry-run",
                "--execute-canary",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(completed.returncode, 3)
        self.assertIn("dry-run", completed.stdout.lower())

    def test_validate_activation_never_outputs_active(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "validate_codex_activation.py")],
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
            cwd=str(REPO_ROOT),
        )
        self.assertNotIn("ACTIVE", completed.stdout)
        self.assertNotIn("EXECUTABLE", completed.stdout)


if __name__ == "__main__":
    unittest.main()