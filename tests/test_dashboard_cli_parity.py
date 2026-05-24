from __future__ import annotations

import tempfile
import sys
import subprocess
import unittest
from pathlib import Path
import yaml

# Resolve the repository root relative to this file
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dashboard.app import create_task_file


class TestDashboardCliParity(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        (self.root / "tasks" / "active").mkdir(parents=True, exist_ok=True)
        (self.root / "tasks" / "done").mkdir(parents=True, exist_ok=True)
        (self.root / "tasks" / "blocked").mkdir(parents=True, exist_ok=True)
        (self.root / "logs").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_cli_dashboard_creation_parity(self) -> None:
        # 1. Create a task via the dashboard helper (which shells out to create_task.py under the hood)
        dashboard_id = create_task_file(
            root_dir=self.root,
            title="Parity Test Task",
            owner="antigravity",
            reviewer="claude",
            objective="Ensure identical outputs.",
            context="This is a test of byte-equal parity between CLI and dashboard.",
            phase="1.7",
            priority="high",
            risk_level="low",
            goals=["Goal 1"],
            acceptance=["Acceptance 1"],
        )

        # 2. Create another task with identical inputs directly using the CLI script
        cli_id = "T-0002"
        script_path = REPO_ROOT / "scripts" / "create_task.py"
        cmd = [
            sys.executable,
            str(script_path),
            "--root",
            str(self.root),
            "--id",
            cli_id,
            "--title",
            "Parity Test Task",
            "--owner",
            "antigravity",
            "--reviewer",
            "claude",
            "--created-by",
            "human",  # Set to human to match dashboard's created_by
            "--objective",
            "Ensure identical outputs.",
            "--context",
            "This is a test of byte-equal parity between CLI and dashboard.",
            "--phase",
            "1.7",
            "--priority",
            "high",
            "--risk-level",
            "low",
            "--goal",
            "Goal 1",
            "--acceptance",
            "Acceptance 1",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        # Verify both files exist
        dashboard_path = self.root / "tasks" / "active" / f"{dashboard_id}.yaml"
        cli_path = self.root / "tasks" / "active" / f"{cli_id}.yaml"

        self.assertTrue(dashboard_path.exists())
        self.assertTrue(cli_path.exists())

        # Load YAML maps
        dashboard_data = yaml.safe_load(dashboard_path.read_text(encoding="utf-8"))
        cli_data = yaml.safe_load(cli_path.read_text(encoding="utf-8"))

        # Compare structures except for timestamps and auto-assigned ID
        for data in (dashboard_data, cli_data):
            self.assertIn("created_at", data)
            self.assertIn("updated_at", data)
            self.assertIn("id", data)

            # Pop time-varying fields and ID for comparison
            data.pop("created_at")
            data.pop("updated_at")
            data.pop("id")
            data.pop("outputs", None)

        # Compare both YAML structures
        self.assertEqual(dashboard_data, cli_data)


if __name__ == "__main__":
    unittest.main()
