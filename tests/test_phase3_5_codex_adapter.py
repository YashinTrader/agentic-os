from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_adapter import (  # noqa: E402
    build_codex_command,
    evaluate_codex_preview_gate,
    load_codex_restricted_adapter,
    version_at_least,
)


class CodexAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = load_codex_restricted_adapter(REPO_ROOT)
        self.repo = REPO_ROOT

    def test_adapter_contract_fields(self) -> None:
        self.assertEqual(self.adapter["id"], "codex-restricted")
        self.assertTrue(self.adapter["supports_execution"])
        self.assertEqual(self.adapter["promotion_state"], "activation_candidate")
        self.assertEqual(self.adapter["execution_scope"], "canary_only")
        self.assertEqual(self.adapter["approval_level"], "human")

    def test_version_at_least(self) -> None:
        self.assertTrue(version_at_least("0.136.0", "0.136.0"))
        self.assertTrue(version_at_least("0.137.1", "0.136.0"))
        self.assertFalse(version_at_least("0.135.0", "0.136.0"))

    def test_build_command_blocks_without_allocation(self) -> None:
        plan = build_codex_command(
            self.adapter,
            repo_root=self.repo,
            worktree_path=str(self.repo),
            run_id="dispatch-test-run",
            stdout_path="out.txt",
            stderr_path="err.txt",
            agent_output_path="agent.txt",
            timeout_seconds=600,
            cli_version="0.136.0",
            allocation_record=None,
            task_id="T-TEST",
            base_sha="abc",
        )
        self.assertTrue(any("allocation" in r for r in plan.blocked_reasons))

    def test_forbidden_flags_block_preview(self) -> None:
        preview = {
            "adapter_id": "codex-restricted",
            "command": "codex exec --dangerously-bypass-approvals-and-sandbox",
        }
        blocked = evaluate_codex_preview_gate(self.adapter, preview, cli_version="0.136.0")
        self.assertTrue(any("forbidden" in b for b in blocked))

    def test_registry_entry_matches_dedicated_config(self) -> None:
        registry = yaml.safe_load(
            (REPO_ROOT / "agents" / "adapter_registry.yaml").read_text(encoding="utf-8")
        )
        entry = next(a for a in registry["adapters"] if a["id"] == "codex-restricted")
        self.assertTrue(entry["supports_execution"])
        self.assertEqual(entry["promotion_state"], "activation_candidate")


if __name__ == "__main__":
    unittest.main()