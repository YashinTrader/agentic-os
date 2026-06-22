from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.execution_gate import evaluate_execution_gates  # noqa: E402
from dispatch.codex_adapter import load_codex_restricted_adapter  # noqa: E402


def _codex_adapter_registry_shape() -> dict:
    return {
        "id": "codex-restricted",
        "status": "active",
        "supports_dry_run": True,
        "supports_execution": False,
        "adapter_type": "cli",
        "writes_files": True,
        "allowed_commands": ["codex"],
        "forbidden_args": ["--dangerously-bypass-approvals-and-sandbox"],
        "required_clis": ["codex"],
        "approval_level": "human",
        "command_template": "",
    }


class CodexExecutorIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        shutil.copytree(
            REPO_ROOT,
            self.root,
            ignore=shutil.ignore_patterns("runtime", ".git", "__pycache__"),
        )
        inv = self.root / "runtime" / "registry"
        inv.mkdir(parents=True, exist_ok=True)
        (inv / "cli_inventory.yaml").write_text(
            yaml.safe_dump(
                {"tools": [{"name": "codex", "available": True, "path": "/usr/bin/codex"}]},
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_execute_blocked_when_supports_execution_false(self) -> None:
        preview = {
            "run_id": "dispatch-codex-1",
            "task_id": "T-CODEX",
            "adapter_id": "codex-restricted",
            "command": "codex exec -C /wt -s workspace-write --json",
            "working_directory": str(self.root),
            "scope_paths": ["."],
            "timeout_seconds": 600,
            "secrets_required": True,
            "dispatch_allowed": True,
            "handoff_path": "handoffs/T-CODEX.md",
            "errors": [],
            "worktree_required": True,
            "base_sha": "a" * 40,
            "approval_gate": {"approval_level": "human", "approval_status": "pending_human"},
            "risk_gate": {"approval_level": "high"},
        }
        cli_inventory = yaml.safe_load(
            (self.root / "runtime/registry/cli_inventory.yaml").read_text(encoding="utf-8")
        )
        gate = evaluate_execution_gates(
            self.root,
            preview,
            adapter=_codex_adapter_registry_shape(),
            cli_inventory=cli_inventory,
            operator_execute=True,
            dry_run=False,
            require_signed_approval=True,
        )
        self.assertFalse(gate.execution_allowed)
        self.assertTrue(
            any("does not support execution" in r for r in gate.blocked_reasons),
            gate.blocked_reasons,
        )

    def test_dedicated_config_remains_non_executable(self) -> None:
        dedicated = load_codex_restricted_adapter(REPO_ROOT)
        self.assertFalse(dedicated["supports_execution"])


if __name__ == "__main__":
    unittest.main()