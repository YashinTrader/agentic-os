from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.approval_signing import build_unsigned_signed_record, sign_approval_record  # noqa: E402
from dispatch.execution_gate import evaluate_execution_gates  # noqa: E402
from dispatch.freshness import compute_preview_hash  # noqa: E402


def _seed_inventory(root: Path) -> None:
    inv_dir = root / "runtime" / "registry"
    inv_dir.mkdir(parents=True, exist_ok=True)
    (inv_dir / "cli_inventory.yaml").write_text(
        yaml.safe_dump(
            {"tools": [{"name": "python", "available": True, "path": sys.executable}]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _base_preview(**overrides) -> dict:
    base = {
        "run_id": "dispatch-20260620T120000Z-phase34",
        "task_id": "T-PHASE34",
        "adapter_id": "local-python-exec-test",
        "command": 'python -c "print(\'agentic-os-executor-test\')"',
        "working_directory": "",
        "scope_paths": ["tasks/"],
        "timeout_seconds": 30,
        "secrets_required": False,
        "dispatch_allowed": True,
        "handoff_path": "handoffs/T-PHASE34__composer__to__claude.md",
        "errors": [],
        "worktree_required": False,
        "approval_gate": {"approval_level": "none", "approval_status": "none"},
        "risk_gate": {"approval_level": "none"},
    }
    base.update(overrides)
    return base


def _local_adapter(**overrides) -> dict:
    base = {
        "id": "local-python-exec-test",
        "status": "active",
        "supports_dry_run": True,
        "supports_execution": True,
        "adapter_type": "cli",
        "writes_files": False,
        "allowed_commands": ["python"],
        "forbidden_args": ["--execute"],
        "required_clis": ["python"],
        "command_template": "",
    }
    base.update(overrides)
    return base


class ExecutorIntegrationTests(unittest.TestCase):
    REVIEWER_KEY = "reviewer-integration-secret"
    HUMAN_KEY = "human-integration-secret"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        shutil.copytree(REPO_ROOT, self.root, ignore=shutil.ignore_patterns("runtime", ".git"))
        self.root = self.root.resolve()
        _seed_inventory(self.root)

        os.environ["AGENTIC_OS_REVIEWER_APPROVAL_KEY"] = self.REVIEWER_KEY
        os.environ["AGENTIC_OS_HUMAN_APPROVAL_KEY"] = self.HUMAN_KEY
        os.environ["AGENTIC_OS_REVIEWER_APPROVAL_KEY_ID"] = "reviewer-int"
        os.environ["AGENTIC_OS_HUMAN_APPROVAL_KEY_ID"] = "human-int"

    def tearDown(self) -> None:
        for name in (
            "AGENTIC_OS_REVIEWER_APPROVAL_KEY",
            "AGENTIC_OS_HUMAN_APPROVAL_KEY",
            "AGENTIC_OS_REVIEWER_APPROVAL_KEY_ID",
            "AGENTIC_OS_HUMAN_APPROVAL_KEY_ID",
        ):
            os.environ.pop(name, None)
        self.tmp.cleanup()

    def _gate(self, preview, *, adapter=None, approval=None, allocation=None, dry_run=False):
        preview = dict(preview)
        preview["working_directory"] = str(self.root)
        resolved_adapter = _local_adapter() if adapter is None else adapter
        cli_inventory = yaml.safe_load(
            (self.root / "runtime/registry/cli_inventory.yaml").read_text(encoding="utf-8")
        )
        return evaluate_execution_gates(
            self.root,
            preview,
            adapter=resolved_adapter,
            cli_inventory=cli_inventory,
            approval_record=approval,
            allocation_record=allocation,
            operator_execute=not dry_run,
            dry_run=dry_run,
            require_signed_approval=True,
        )

    def test_file_writing_without_allocation_blocks(self) -> None:
        preview = _base_preview(
            worktree_required=True,
            base_sha="abc1234567890abcdef1234567890abcdef123456",
        )
        adapter = _local_adapter(writes_files=True)
        result = self._gate(preview, adapter=adapter, dry_run=True)
        self.assertFalse(result.execution_allowed)
        blocked = " ".join(result.blocked_reasons).lower()
        self.assertTrue(
            "allocation" in blocked or "worktree" in blocked,
            result.blocked_reasons,
        )

    def test_signed_approval_path_allows_reviewer_gate(self) -> None:
        preview = _base_preview(
            approval_gate={"approval_level": "reviewer", "approval_status": "pending_reviewer"},
        )
        adapter = _local_adapter()
        working_preview = {**preview, "working_directory": str(self.root)}
        preview_hash = compute_preview_hash(working_preview, adapter=adapter)
        command = str(preview["command"])
        cmd_hash = hashlib.sha256(command.encode("utf-8")).hexdigest()

        unsigned = build_unsigned_signed_record(
            approval_id="approval-integration-001",
            task_id=preview["task_id"],
            run_id=preview["run_id"],
            preview_id=preview["run_id"],
            preview_hash=preview_hash,
            adapter_id=preview["adapter_id"],
            approval_level="reviewer",
            approver_type="reviewer",
            approved_by="integration-reviewer",
            allowed_command_hash=cmd_hash,
            allowed_cwd=str(self.root),
            allowed_scope_paths=list(preview["scope_paths"]),
            nonce="integration-nonce",
        )
        unsigned["approved_at"] = unsigned["issued_at"]
        unsigned["scope"] = "dispatch_execution"

        signed = sign_approval_record(unsigned, approver_type="reviewer")
        self.assertTrue(signed.success, signed.errors)
        assert signed.record is not None

        result = self._gate(working_preview, adapter=adapter, approval=signed.record, dry_run=True)
        self.assertTrue(result.execution_allowed, result.blocked_reasons)
        self.assertEqual(result.approval_status, "approved")


if __name__ == "__main__":
    unittest.main()