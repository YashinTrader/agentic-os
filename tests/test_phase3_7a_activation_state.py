from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_adapter import load_codex_restricted_adapter  # noqa: E402
from dispatch.execution_gate import adapter_supports_execution  # noqa: E402


class Phase37aActivationStateTests(unittest.TestCase):
    def test_adapter_activation_candidate_config(self) -> None:
        adapter = load_codex_restricted_adapter(REPO_ROOT)
        self.assertEqual(adapter["id"], "codex-restricted")
        self.assertEqual(adapter["promotion_state"], "activation_candidate")
        self.assertTrue(adapter["supports_execution"])
        self.assertEqual(adapter["execution_scope"], "canary_only")
        self.assertEqual(adapter["maximum_runs"], 1)
        self.assertTrue(adapter["automatic_disable_after_run"])
        self.assertFalse(adapter["live_run_authorized"])
        self.assertTrue(adapter["phase3_7b_authorization_required"])
        self.assertTrue(adapter["worktree_required"])
        self.assertTrue(adapter["network_required"])
        self.assertTrue(adapter["secrets_required"])
        self.assertFalse(adapter["mcp_required"])
        self.assertEqual(adapter["approval_level"], "human")

    def test_registry_matches_dedicated_config(self) -> None:
        registry = yaml.safe_load(
            (REPO_ROOT / "agents" / "adapter_registry.yaml").read_text(encoding="utf-8")
        )
        entry = next(a for a in registry["adapters"] if a["id"] == "codex-restricted")
        dedicated = load_codex_restricted_adapter(REPO_ROOT)
        for key in (
            "promotion_state",
            "supports_execution",
            "execution_scope",
            "maximum_runs",
            "approval_level",
        ):
            self.assertEqual(entry.get(key), dedicated.get(key), key)

    def test_supports_execution_does_not_imply_live_run(self) -> None:
        registry = yaml.safe_load(
            (REPO_ROOT / "agents" / "adapter_registry.yaml").read_text(encoding="utf-8")
        )
        entry = next(a for a in registry["adapters"] if a["id"] == "codex-restricted")
        self.assertTrue(adapter_supports_execution(entry))
        self.assertFalse(entry.get("live_run_authorized", True))


if __name__ == "__main__":
    unittest.main()