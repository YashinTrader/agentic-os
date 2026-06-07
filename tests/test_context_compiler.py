from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

from orchestrator.context_compiler import compile_context_json, compile_context_markdown, write_context_pack


class ContextCompilerTests(unittest.TestCase):
    def test_writes_markdown_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run-1"
            state = {
                "task_id": "T-TEST",
                "run_id": "run-1",
                "title": "Test",
                "objective": "Verify compiler",
                "required_skills": ["implement-python-cli"],
                "selected_team": "coding-team",
                "selected_team_score": 20,
                "selected_agents": ["codex"],
                "recommended_primary_agent": "codex",
                "recommended_reviewer": "claude",
                "required_mcps": [],
                "recent_handoffs": [],
                "recent_events": [],
                "files_to_inspect": ["scripts/"],
                "recommended_prompt": "Do the work.",
            }
            md_path, json_path = write_context_pack(run_dir, state, dry_run=False)
            self.assertTrue(Path(md_path).exists())
            self.assertTrue(Path(json_path).exists())
            md = Path(md_path).read_text(encoding="utf-8")
            self.assertIn("Context Pack: T-TEST", md)
            data = json.loads(Path(json_path).read_text(encoding="utf-8"))
            self.assertEqual(data["task_id"], "T-TEST")

    def test_markdown_includes_sections(self) -> None:
        md = compile_context_markdown(
            {
                "task_id": "T-1",
                "title": "Dashboard",
                "objective": "Build UI",
                "task_data": {"constraints": ["no agents"], "acceptance": ["tests pass"]},
                "selected_team": "dashboard-team",
                "selected_team_score": 10,
                "required_skills": ["build-streamlit-dashboard"],
                "selected_agents": ["gemini"],
                "recommended_primary_agent": "gemini",
                "recommended_reviewer": "claude",
                "required_mcps": [],
                "recent_handoffs": [],
                "recent_events": [],
                "files_to_inspect": [],
                "recommended_prompt": "prompt",
            }
        )
        self.assertIn("## Acceptance Criteria", md)
        self.assertIn("## Recommended Prompt For Agent", md)
        payload = compile_context_json({"task_id": "T-1", "selected_team": "dashboard-team"})
        self.assertEqual(payload["task_id"], "T-1")


if __name__ == "__main__":
    unittest.main()