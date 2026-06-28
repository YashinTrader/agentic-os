from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.executor_contract import (  # noqa: E402
    ExecutionRequest,
    build_execution_request_from_preview,
    resolve_mcp_required,
    validate_cli_inventory_gate,
    validate_execution_request_contract,
)


def _base_request(**overrides) -> ExecutionRequest:
    defaults = dict(
        run_id="dispatch-20260611T120000Z-abc12345",
        task_id="T-PHASE3-1-DESIGN",
        plan_path="runtime/orchestrator/latest_plan.json",
        preview_path="runtime/dispatch/previews/dispatch-20260611T120000Z-abc12345/preview.json",
        adapter_id="composer-cli-preview",
        selected_agent="composer",
        command_preview="composer agent run --dry-run --task-id T-PHASE3-1-DESIGN",
        cwd=str(REPO_ROOT),
        scope_paths=("tasks/", "handoffs/"),
        timeout_seconds=300,
        approval_level="reviewer",
        approval_status="approved",
        approval_record_path="runtime/dispatch/runs/dispatch-20260611T120000Z-abc12345/approval_record.json",
        worktree_required=False,
        writes_files=False,
        secrets_required=False,
        network_required=False,
        mcp_required=False,
        executed=False,
        execution_allowed=False,
    )
    defaults.update(overrides)
    return ExecutionRequest(**defaults)


class ExecutorContractTests(unittest.TestCase):
    def test_module_has_no_subprocess(self) -> None:
        source = (REPO_ROOT / "dispatch" / "executor_contract.py").read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("subprocess.", source)
        self.assertNotIn("os.system", source)
        self.assertNotIn("os.popen", source)

    def test_valid_request_passes_contract(self) -> None:
        adapter = {
            "id": "composer-cli-preview",
            "status": "active",
            "supports_dry_run": True,
            "required_clis": [],
            "writes_files": False,
        }
        result = validate_execution_request_contract(_base_request(), adapter=adapter)
        self.assertTrue(result.valid)
        self.assertTrue(result.execution_allowed)
        self.assertEqual(result.blocked_reasons, [])

    def test_missing_adapter_blocks_execution(self) -> None:
        result = validate_execution_request_contract(_base_request(), adapter=None)
        self.assertFalse(result.execution_allowed)
        self.assertTrue(any("not found" in r for r in result.blocked_reasons))

    def test_writes_files_without_worktree_blocks(self) -> None:
        adapter = {
            "id": "codex-cli-preview",
            "status": "active",
            "supports_dry_run": True,
            "required_clis": ["codex"],
            "writes_files": True,
        }
        request = _base_request(writes_files=True, worktree_required=False)
        result = validate_execution_request_contract(request, adapter=adapter)
        self.assertFalse(result.execution_allowed)
        self.assertTrue(any("worktree_required" in r for r in result.blocked_reasons))

    def test_secrets_required_implies_human_approval(self) -> None:
        adapter = {
            "id": "composer-cli-preview",
            "status": "active",
            "supports_dry_run": True,
            "required_clis": [],
            "writes_files": False,
        }
        request = _base_request(secrets_required=True, approval_level="reviewer")
        result = validate_execution_request_contract(request, adapter=adapter)
        self.assertFalse(result.execution_allowed)
        self.assertTrue(any("secrets_required" in r for r in result.blocked_reasons))

    def test_cli_inventory_gate_missing_tool(self) -> None:
        adapter = {"required_clis": ["codex", "composer"]}
        inventory = {
            "tools": [
                {"name": "composer", "available": True, "path": "/usr/bin/composer"},
            ]
        }
        errors = validate_cli_inventory_gate(adapter, inventory)
        self.assertTrue(any("codex" in e and "not found" in e for e in errors))

    def test_cli_inventory_gate_unavailable_tool(self) -> None:
        adapter = {"required_clis": ["codex"]}
        inventory = {
            "tools": [
                {"name": "codex", "available": False, "path": "/usr/bin/codex"},
            ]
        }
        errors = validate_cli_inventory_gate(adapter, inventory)
        self.assertTrue(any("not available" in e for e in errors))

    def test_invalid_timeout_reports_invalid_not_missing(self) -> None:
        adapter = {
            "id": "composer-cli-preview",
            "status": "active",
            "supports_dry_run": True,
            "required_clis": [],
            "writes_files": False,
        }
        request = _base_request(timeout_seconds=0)
        result = validate_execution_request_contract(request, adapter=adapter)
        self.assertFalse(result.execution_allowed)
        self.assertTrue(any("invalid: timeout_seconds" in r for r in result.blocked_reasons))
        self.assertFalse(any("missing: timeout_seconds" in r for r in result.blocked_reasons))

    def test_adapter_id_suffix_does_not_imply_mcp_required(self) -> None:
        preview = {
            "run_id": "dispatch-test",
            "task_id": "T-1",
            "plan_path": "runtime/orchestrator/latest_plan.json",
            "adapter_id": "blocked-mcp-preview",
            "agent_id": "mcp",
            "command": "mcp invoke --dry-run",
            "working_directory": str(REPO_ROOT),
            "scope_paths": [],
            "timeout_seconds": 60,
            "secrets_required": False,
            "dispatch_allowed": False,
            "approval_gate": {"approval_level": "blocked", "approval_status": "blocked"},
            "errors": [],
        }
        adapter_cli_suffix = {
            "id": "blocked-mcp-preview",
            "adapter_type": "cli",
            "writes_files": False,
            "working_directory_policy": "repo_root",
        }
        request = build_execution_request_from_preview(preview, adapter=adapter_cli_suffix)
        self.assertFalse(request.mcp_required)

    def test_adapter_type_mcp_sets_mcp_required(self) -> None:
        adapter = {
            "id": "blocked-mcp-preview",
            "adapter_type": "mcp",
            "writes_files": False,
            "working_directory_policy": "repo_root",
        }
        self.assertTrue(resolve_mcp_required(adapter))
        preview = {
            "run_id": "dispatch-test",
            "task_id": "T-1",
            "plan_path": "runtime/orchestrator/latest_plan.json",
            "adapter_id": "blocked-mcp-preview",
            "agent_id": "mcp",
            "command": "mcp invoke --dry-run",
            "working_directory": str(REPO_ROOT),
            "scope_paths": [],
            "timeout_seconds": 60,
            "secrets_required": False,
            "dispatch_allowed": False,
            "approval_gate": {"approval_level": "blocked", "approval_status": "blocked"},
            "errors": [],
        }
        request = build_execution_request_from_preview(preview, adapter=adapter)
        self.assertTrue(request.mcp_required)

    def test_docs_and_adrs_exist(self) -> None:
        for rel in (
            "docs/PHASE_3_1_EXECUTOR_DESIGN.md",
            "docs/PHASE_3_1_APPROVAL_MODEL.md",
            "docs/PHASE_3_1_WORKTREE_SANDBOX_STRATEGY.md",
            "docs/PHASE_3_1_RUNTIME_CAPTURE_CONTRACT.md",
            "decisions/ADR-0014-phase-3-1-controlled-executor-contract.md",
            "decisions/ADR-0015-approval-recording-and-preview-freshness.md",
            "decisions/ADR-0016-worktree-sandbox-before-file-writing-execution.md",
        ):
            self.assertTrue((REPO_ROOT / rel).exists(), rel)


if __name__ == "__main__":
    unittest.main()