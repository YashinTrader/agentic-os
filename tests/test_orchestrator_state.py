from __future__ import annotations

import json
import unittest

from orchestrator.state import OrchestratorState


class OrchestratorStateTests(unittest.TestCase):
    def test_state_is_json_serializable(self) -> None:
        state = OrchestratorState(
            run_id="run-test",
            task_id="T-TEST",
            required_skills=["implement-python-cli"],
            candidate_teams=[{"team_id": "coding-team", "score": 10}],
            errors=["none"],
            warnings=["warn"],
        )
        parsed = json.loads(state.to_json())
        self.assertEqual(parsed["task_id"], "T-TEST")
        self.assertEqual(parsed["required_skills"], ["implement-python-cli"])

    def test_from_dict_roundtrip(self) -> None:
        original = OrchestratorState(run_id="r1", task_id="T-1", title="Title")
        restored = OrchestratorState.from_dict(original.to_dict())
        self.assertEqual(restored.run_id, "r1")
        self.assertEqual(restored.title, "Title")


if __name__ == "__main__":
    unittest.main()