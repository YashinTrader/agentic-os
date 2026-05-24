from __future__ import annotations

import unittest
from pathlib import Path

# We will import the parsing functions directly from dashboard.app
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.app import load_all_tasks, load_events

ROOT_DIR = Path(__file__).resolve().parents[1]


class TestDashboardRealRepo(unittest.TestCase):
    def test_real_repo_parsing(self) -> None:
        tasks, task_errors = load_all_tasks(ROOT_DIR)
        events, event_errors = load_events(ROOT_DIR)
        
        # In a healthy clone, we should have at least 1 task (e.g. T-0001, T-0013)
        self.assertGreaterEqual(len(tasks), 1, "Should have at least 1 task in the live repository")
        
        # Assert at least one task parses successfully with non-empty objective/goals and acceptance list
        parsed_valid_task = False
        for t in tasks:
            # Verify required schema v2 parsed fields are non-empty
            if t.get("id") and t.get("objective") and isinstance(t.get("goals"), list) and isinstance(t.get("acceptance"), list):
                if len(t.get("goals")) > 0 and len(t.get("acceptance")) > 0:
                    parsed_valid_task = True
                    break
        
        self.assertTrue(parsed_valid_task, "Failed to parse at least one valid schema v2 task in actual repository")


if __name__ == "__main__":
    unittest.main()
