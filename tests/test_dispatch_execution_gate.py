from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.approval_contract import ApprovalRecord  # noqa: E402
from dispatch.execution_gate import evaluate_execution_gates  # noqa: E402
from dispatch.freshness import compute_preview_hash  # noqa: E402


def _seed_inventory(root: Path, tools: list[dict]) -> None:
    inv_dir = root / "runtime" / "registry"
    inv_dir.mkdir(parents=True, exist_ok=True)
    (inv_dir / "cli_inventory.yaml").write_text(
        yaml.safe_dump({"tools": tools}, sort_keys=False),
        encoding="utf-8",
    )


def _base_preview(**overrides) -> dict:
    base = {
        "run_id": "dispatch-20260612T120000Z-gate0001",
        "task_id": "T-GATE",
        "adapter_id": "local-python-exec-test",
        "command": 'python -c "print(\'agentic-os-executor-test\')"',
        "working_directory": "",
        "scope_paths": ["tasks/"],
        "timeout_seconds": 30,
        "secrets_required": False,
        "dispatch_allowed": True,
        "handoff_path": "handoffs/T-GATE__composer__to__claude.md",
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


class ExecutionGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        shutil.copytree(REPO_ROOT, self.root, ignore=shutil.ignore_patterns("runtime", ".git"))
        self.root = self.root.resolve()
        _seed_inventory(
            self.root,
            [{"name": "python", "available": True, "path": sys.executable}],
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _gate(self, preview, *, adapter=None, approval=None, execute=False, dry_run=False):
        preview = dict(preview)
        preview["working_directory"] = str(self.root)
        resolved_adapter = _local_adapter() if adapter is None else adapter
        return evaluate_execution_gates(
            self.root,
            preview,
            adapter=resolved_adapter,
            cli_inventory=yaml.safe_load(
                (self.root / "runtime/registry/cli_inventory.yaml").read_text(encoding="utf-8")
            ),
            approval_record=approval,
            operator_execute=execute,
            dry_run=dry_run,
        )

    def test_no_explicit_execute_or_dry_run_blocks(self) -> None:
        result = self._gate(_base_preview())
        self.assertFalse(result.execution_allowed)

    def test_dry_run_passes_gates(self) -> None:
        result = self._gate(_base_preview(), dry_run=True)
        self.assertTrue(result.execution_allowed)

    def test_missing_adapter_blocks(self) -> None:
        preview = _base_preview(adapter_id="missing")
        result = evaluate_execution_gates(
            self.root,
            {**preview, "working_directory": str(self.root)},
            adapter=None,
            cli_inventory={"tools": [{"name": "python", "available": True, "path": sys.executable}]},
            dry_run=True,
        )
        self.assertFalse(result.execution_allowed)

    def test_inactive_adapter_blocks(self) -> None:
        result = self._gate(_base_preview(), adapter=_local_adapter(status="disabled"), dry_run=True)
        self.assertFalse(result.execution_allowed)

    def test_missing_cli_blocks(self) -> None:
        result = self._gate(
            _base_preview(),
            adapter=_local_adapter(required_clis=["nonexistent-cli"]),
            dry_run=True,
        )
        self.assertFalse(result.execution_allowed)

    def test_human_required_without_approval_blocks(self) -> None:
        preview = _base_preview(
            approval_gate={"approval_level": "human", "approval_status": "pending_human"},
        )
        result = self._gate(preview, dry_run=True)
        self.assertFalse(result.execution_allowed)

    def test_stale_approval_blocks(self) -> None:
        preview = _base_preview(
            approval_gate={"approval_level": "reviewer", "approval_status": "pending_reviewer"},
        )
        adapter = _local_adapter()
        digest = compute_preview_hash(preview, adapter=adapter)
        record = {
            "approval_id": "a",
            "task_id": "T",
            "run_id": preview["run_id"],
            "preview_hash": "b" * 64,
            "adapter_id": "local-python-exec-test",
            "approval_level": "reviewer",
            "approved_by": "c",
            "approver_type": "reviewer",
            "approved_at": "2026-06-12T12:00:00Z",
            "expires_at": "2026-06-12T14:00:00Z",
            "scope": "s",
            "allowed_command_hash": "h",
            "allowed_cwd": str(self.root),
            "allowed_scope_paths": ["tasks/"],
            "revoked": False,
        }
        result = self._gate(preview, approval=record, dry_run=True)
        self.assertFalse(result.execution_allowed)
        self.assertEqual(result.approval_status, "stale")

    def test_expired_approval_blocks(self) -> None:
        preview = _base_preview(
            approval_gate={"approval_level": "reviewer", "approval_status": "pending_reviewer"},
        )
        adapter = _local_adapter()
        digest = compute_preview_hash({**preview, "working_directory": str(self.root)}, adapter=adapter)
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(microsecond=0)
        record = ApprovalRecord(
            approval_id="a",
            task_id="T",
            run_id=preview["run_id"],
            preview_hash=digest,
            adapter_id="local-python-exec-test",
            approval_level="reviewer",
            approved_by="c",
            approver_type="reviewer",
            approved_at=past.isoformat().replace("+00:00", "Z"),
            expires_at=(past + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            scope="s",
            allowed_command_hash="h",
            allowed_cwd=str(self.root),
            allowed_scope_paths=(),
        )
        result = evaluate_execution_gates(
            self.root,
            {**preview, "working_directory": str(self.root)},
            adapter=adapter,
            cli_inventory={"tools": [{"name": "python", "available": True, "path": sys.executable}]},
            approval_record={
                **record.__dict__,
                "allowed_scope_paths": ["tasks/"],
            },
            dry_run=True,
            now=datetime.now(timezone.utc),
        )
        self.assertFalse(result.execution_allowed)
        self.assertEqual(result.approval_status, "expired")

    def test_revoked_approval_blocks(self) -> None:
        preview = _base_preview(
            approval_gate={"approval_level": "reviewer", "approval_status": "pending_reviewer"},
        )
        adapter = _local_adapter()
        digest = compute_preview_hash({**preview, "working_directory": str(self.root)}, adapter=adapter)
        record = {
            "approval_id": "a",
            "task_id": "T",
            "run_id": preview["run_id"],
            "preview_hash": digest,
            "adapter_id": "local-python-exec-test",
            "approval_level": "reviewer",
            "approved_by": "c",
            "approver_type": "reviewer",
            "approved_at": "2026-06-12T12:00:00Z",
            "expires_at": "2026-06-12T14:00:00Z",
            "scope": "s",
            "allowed_command_hash": "h",
            "allowed_cwd": str(self.root),
            "allowed_scope_paths": ["tasks/"],
            "revoked": True,
        }
        result = self._gate(preview, approval=record, dry_run=True)
        self.assertFalse(result.execution_allowed)
        self.assertEqual(result.approval_status, "revoked")

    def test_writes_files_without_worktree_blocks(self) -> None:
        preview = _base_preview(worktree_required=True)
        adapter = _local_adapter(writes_files=True)
        result = self._gate(preview, adapter=adapter, dry_run=True)
        self.assertFalse(result.execution_allowed)

    def test_mcp_required_blocks(self) -> None:
        preview = _base_preview()
        adapter = _local_adapter(adapter_type="mcp")
        result = self._gate(preview, adapter=adapter, dry_run=True)
        self.assertFalse(result.execution_allowed)

    def test_secrets_required_without_human_blocks(self) -> None:
        preview = _base_preview(secrets_required=True, approval_gate={"approval_level": "reviewer"})
        result = self._gate(preview, dry_run=True)
        self.assertFalse(result.execution_allowed)

    def test_high_risk_requires_human(self) -> None:
        preview = _base_preview(
            risk_gate={"approval_level": "human"},
            approval_gate={"approval_level": "reviewer", "approval_status": "pending_reviewer"},
        )
        adapter = _local_adapter()
        digest = compute_preview_hash({**preview, "working_directory": str(self.root)}, adapter=adapter)
        record = {
            "approval_id": "a",
            "task_id": "T",
            "run_id": preview["run_id"],
            "preview_hash": digest,
            "adapter_id": "local-python-exec-test",
            "approval_level": "reviewer",
            "approved_by": "c",
            "approver_type": "reviewer",
            "approved_at": "2026-06-12T12:00:00Z",
            "expires_at": "2026-06-12T14:00:00Z",
            "scope": "s",
            "allowed_command_hash": "h",
            "allowed_cwd": str(self.root),
            "allowed_scope_paths": ["tasks/"],
            "revoked": False,
        }
        result = self._gate(preview, approval=record, dry_run=True)
        self.assertFalse(result.execution_allowed)

    def test_non_execution_adapter_blocks_execute(self) -> None:
        preview = _base_preview(adapter_id="composer-cli-preview")
        adapter = {
            "id": "composer-cli-preview",
            "status": "active",
            "supports_dry_run": True,
            "adapter_type": "cli",
            "writes_files": False,
            "allowed_commands": ["composer"],
            "forbidden_args": [],
            "required_clis": [],
        }
        preview["command"] = "composer agent run --dry-run"
        preview["working_directory"] = str(self.root)
        result = evaluate_execution_gates(
            self.root,
            preview,
            adapter=adapter,
            cli_inventory={"tools": []},
            operator_execute=True,
            dry_run=False,
        )
        self.assertFalse(result.execution_allowed)
        self.assertTrue(any("does not support execution" in r for r in result.blocked_reasons))


if __name__ == "__main__":
    unittest.main()