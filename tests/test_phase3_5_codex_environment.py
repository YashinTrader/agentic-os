from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.agent_environment import (  # noqa: E402
    build_minimal_environment,
    environment_preview,
    redact_environment_for_log,
)


class CodexEnvironmentTests(unittest.TestCase):
    def test_denylist_strips_secrets(self) -> None:
        parent = {
            "PATH": "/usr/bin",
            "OPENAI_API_KEY": "sk-fake-secret",
            "AGENTIC_OS_HUMAN_APPROVAL_KEY": "hmac-secret",
            "GITHUB_TOKEN": "ghp_fake",
        }
        env, names = build_minimal_environment(parent)
        self.assertIn("PATH", env)
        self.assertIn("OPENAI_API_KEY", env)
        self.assertNotIn("AGENTIC_OS_HUMAN_APPROVAL_KEY", env)
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("AGENTIC_OS_HUMAN_APPROVAL_KEY", names)

    def test_preview_lists_names_not_values(self) -> None:
        adapter = {
            "environment_allowlist": ["PATH", "OPENAI_API_KEY"],
            "environment_denylist": ["GITHUB_TOKEN"],
            "secrets_required": True,
        }
        preview = environment_preview(
            adapter,
            parent_env={"PATH": "/x", "OPENAI_API_KEY": "secret-value", "GITHUB_TOKEN": "gh"},
        )
        text = str(preview)
        self.assertNotIn("secret-value", text)
        self.assertNotIn("gh", text)
        self.assertIn("OPENAI_API_KEY", preview["environment_variable_names"])

    def test_redact_environment_for_log(self) -> None:
        redacted = redact_environment_for_log({"OPENAI_API_KEY": "sk-test"})
        self.assertEqual(redacted["OPENAI_API_KEY"], "<redacted>")


if __name__ == "__main__":
    unittest.main()