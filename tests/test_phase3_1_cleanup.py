"""Regression tests for Phase 3.1 cleanup items (Subphase A)."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.approval_contract import (  # noqa: E402
    DEFAULT_HUMAN_APPROVAL_TTL_MINUTES,
    DEFAULT_REVIEWER_APPROVAL_TTL_MINUTES,
    evaluate_approval_satisfaction,
    validate_approval_record_shape,
)
from dispatch.executor_contract import (  # noqa: E402
    build_execution_request_from_preview,
    resolve_mcp_required,
    validate_execution_request_contract,
    ExecutionRequest,
)
from dispatch.preview import validate_key_value_forbidden_args  # noqa: E402


def _sample_record(**overrides):
    from dispatch.approval_contract import ApprovalRecord

    base = dict(
        approval_id="apr-cleanup",
        task_id="T-CLEANUP",
        run_id="dispatch-test",
        preview_hash="a" * 64,
        adapter_id="composer-cli-preview",
        approval_level="reviewer",
        approved_by="composer",
        approver_type="reviewer",
        approved_at="2026-06-12T12:00:00Z",
        expires_at="2026-06-12T13:00:00Z",
        scope="dispatch",
        allowed_command_hash="abc",
        allowed_cwd=str(REPO_ROOT),
        allowed_scope_paths=("tasks/",),
        revoked=False,
    )
    base.update(overrides)
    return ApprovalRecord(**base)


class Phase31CleanupTests(unittest.TestCase):
    def test_shape_vs_satisfaction_split(self) -> None:
        shape = validate_approval_record_shape(_sample_record())
        self.assertTrue(shape.well_formed)
        sat = evaluate_approval_satisfaction(None, "a" * 64, "reviewer")
        self.assertFalse(sat.satisfied)
        self.assertEqual(sat.status, "pending")

    def test_revoked_uses_structured_status_not_substring(self) -> None:
        result = evaluate_approval_satisfaction(_sample_record(revoked=True), "a" * 64, "reviewer")
        self.assertEqual(result.status, "revoked")
        self.assertEqual(result.reasons, ["approval record is revoked"])

    def test_mcp_required_from_adapter_type_not_id_suffix(self) -> None:
        adapter = {"id": "blocked-mcp-preview", "adapter_type": "cli"}
        self.assertFalse(resolve_mcp_required(adapter))
        self.assertTrue(resolve_mcp_required({"adapter_type": "mcp"}))

    def test_missing_vs_invalid_field_messages(self) -> None:
        request = ExecutionRequest(
            run_id="",
            task_id="T-1",
            plan_path="p",
            preview_path="p",
            adapter_id="a",
            selected_agent="c",
            command_preview="cmd",
            cwd="/tmp",
            scope_paths=(),
            timeout_seconds=0,
            approval_level="invalid-level",
            approval_status="approved",
            approval_record_path=None,
            worktree_required=False,
            writes_files=False,
            secrets_required=False,
            network_required=False,
            mcp_required=False,
        )
        result = validate_execution_request_contract(
            request,
            adapter={"id": "a", "status": "active", "supports_dry_run": True, "required_clis": []},
        )
        self.assertTrue(any("missing: run_id" in r for r in result.blocked_reasons))
        self.assertTrue(any("invalid: timeout_seconds" in r for r in result.blocked_reasons))
        self.assertTrue(
            any("approval_level" in r and "invalid:" in r for r in result.blocked_reasons)
        )

    def test_default_ttl_constants(self) -> None:
        self.assertEqual(DEFAULT_HUMAN_APPROVAL_TTL_MINUTES, 30)
        self.assertEqual(DEFAULT_REVIEWER_APPROVAL_TTL_MINUTES, 60)

    def test_forbidden_args_dual_duty_exact_and_key_value(self) -> None:
        adapter = {"forbidden_args": ["--execute", "rm"]}
        token_errors = validate_key_value_forbidden_args(adapter, "tool --execute=true")
        self.assertTrue(any("forbidden argument key" in e for e in token_errors))

    def test_build_execution_request_mcp_from_metadata(self) -> None:
        preview = {
            "run_id": "r",
            "task_id": "T",
            "adapter_id": "x-mcp-suffix",
            "agent_id": "x",
            "command": "cmd",
            "working_directory": str(REPO_ROOT),
            "scope_paths": [],
            "timeout_seconds": 30,
            "secrets_required": False,
            "approval_gate": {"approval_level": "none", "approval_status": "none"},
            "errors": [],
        }
        request = build_execution_request_from_preview(
            preview,
            adapter={"id": "x-mcp-suffix", "adapter_type": "cli", "writes_files": False},
        )
        self.assertFalse(request.mcp_required)


if __name__ == "__main__":
    unittest.main()