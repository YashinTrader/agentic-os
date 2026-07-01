"""Phase 3.7A.1 — H1 main-executor bypass closure regression tests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.approval_signing import build_unsigned_signed_record, sign_approval_record  # noqa: E402
from dispatch.codex_activation_gate import (  # noqa: E402
    PHASE3_7B_BLOCKED_REASON,
    evaluate_activation_gates,

)
from dispatch.codex_adapter import load_codex_restricted_adapter  # noqa: E402
from dispatch.execution_gate import evaluate_execution_gates  # noqa: E402
from dispatch.execution_route_policy import (  # noqa: E402
    DEDICATED_CANARY_RUNNER_REASON,
    ROUTE_CODEX_CANARY,
    ROUTE_CODEX_LOCAL_BUILDER,
    ROUTE_GENERIC_DISPATCH,
    ROUTE_PREVIEW_ONLY,
    evaluate_execution_route,
    validate_adapter_route_policy,
)
from dispatch.executor import execute_dispatch  # noqa: E402
from dispatch.freshness import compute_preview_hash  # noqa: E402
from dispatch.preview import build_dispatch_preview, persist_preview  # noqa: E402

BASE_SHA = "a" * 40
RUN_ID = "dispatch-20260629T120000Z-codex-h1"
TASK_ID = "T-CODEX-H1"
HUMAN_KEY = "human-h1-bypass-secret"
REVIEWER_KEY = "reviewer-h1-bypass-secret"


def _local_adapter() -> dict:
    return {
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


def _canary_fixture_adapter() -> dict:
    """Canary-era adapter shape for activation-gate regression (not live local-worktree config)."""
    return {
        "id": "codex-restricted",
        "status": "active",
        "supports_dry_run": True,
        "supports_execution": True,
        "execution_scope": "canary_only",
        "dedicated_runner_required": True,
        "required_execution_route": ROUTE_CODEX_CANARY,
        "phase3_7b_authorization_required": True,
        "promotion_state": "activation_candidate",
        "adapter_type": "cli",
        "writes_files": True,
        "allowed_commands": ["codex"],
        "forbidden_args": ["--dangerously-bypass-approvals-and-sandbox"],
        "required_clis": ["codex"],
        "approval_level": "human",
        "command_template": "",
    }


class CodexH1FixtureMixin:
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        shutil.copytree(
            REPO_ROOT,
            self.root,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "runtime/dispatch/runs/*"),
        )
        self._seed_context()
        os.environ["AGENTIC_OS_HUMAN_APPROVAL_KEY"] = HUMAN_KEY
        os.environ["AGENTIC_OS_REVIEWER_APPROVAL_KEY"] = REVIEWER_KEY
        os.environ["AGENTIC_OS_HUMAN_APPROVAL_KEY_ID"] = "human-h1"
        os.environ["AGENTIC_OS_REVIEWER_APPROVAL_KEY_ID"] = "reviewer-h1"

    def tearDown(self) -> None:
        for name in (
            "AGENTIC_OS_HUMAN_APPROVAL_KEY",
            "AGENTIC_OS_REVIEWER_APPROVAL_KEY",
            "AGENTIC_OS_HUMAN_APPROVAL_KEY_ID",
            "AGENTIC_OS_REVIEWER_APPROVAL_KEY_ID",
        ):
            os.environ.pop(name, None)
        self.tmp.cleanup()

    def _seed_context(self) -> None:
        task_dir = self.root / "tasks" / "active"
        task_dir.mkdir(parents=True, exist_ok=True)
        task = {
            "id": TASK_ID,
            "title": "Codex H1 bypass regression",
            "owner": "composer",
            "reviewer": "claude",
            "created_by": "composer",
            "status": "ready",
            "phase": "3.7",
            "created_at": "2026-06-29T12:00:00Z",
            "updated_at": "2026-06-29T12:00:00Z",
            "priority": "high",
            "risk_level": "high",
            "requires_human_approval": True,
            "human_approval_checklist": [],
            "objective": "H1 regression",
            "context": "test",
            "goals": [],
            "non_goals": [],
            "inputs": [],
            "outputs": [],
            "constraints": [],
            "acceptance": [],
            "notes": "",
        }
        (task_dir / f"{TASK_ID}.yaml").write_text(yaml.safe_dump(task, sort_keys=False), encoding="utf-8")
        orch = self.root / "runtime" / "orchestrator"
        orch.mkdir(parents=True, exist_ok=True)
        plan = {
            "run_id": "run-h1",
            "task_id": TASK_ID,
            "recommended_primary_agent": "codex",
            "recommended_reviewer": "claude",
            "approval_level": "human",
            "approval_required": True,
            "files_to_inspect": [],
        }
        (orch / "latest_plan.json").write_text(json.dumps(plan), encoding="utf-8")
        state = {
            "run_id": "run-h1",
            "task_id": TASK_ID,
            "task_path": f"tasks/active/{TASK_ID}.yaml",
            "plan_path": "runtime/orchestrator/latest_plan.json",
            "approval_level": "human",
            "risk_level": "high",
        }
        (orch / "latest_state.json").write_text(json.dumps(state), encoding="utf-8")
        inv_dir = self.root / "runtime" / "registry"
        inv_dir.mkdir(parents=True, exist_ok=True)
        (inv_dir / "cli_inventory.yaml").write_text(
            yaml.safe_dump(
                {"tools": [{"name": "codex", "available": True, "path": "/usr/bin/codex"}]},
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def _worktree_paths(self) -> tuple[Path, Path]:
        wt_root = self.root / "runtime" / "worktrees"
        wt_path = wt_root / "wt-codex-h1"
        wt_path.mkdir(parents=True, exist_ok=True)
        return wt_root, wt_path

    def _codex_adapter(self) -> dict:
        registry = yaml.safe_load(
            (self.root / "agents" / "adapter_registry.yaml").read_text(encoding="utf-8")
        )
        return next(a for a in registry["adapters"] if a["id"] == "codex-restricted")

    def _codex_preview(self, **overrides) -> dict:
        _, wt_path = self._worktree_paths()
        command = f"codex exec -C {wt_path} -s workspace-write --json"
        base = {
            "run_id": RUN_ID,
            "task_id": TASK_ID,
            "adapter_id": "codex-restricted",
            "command": command,
            "working_directory": str(wt_path),
            "scope_paths": ["."],
            "timeout_seconds": 600,
            "secrets_required": True,
            "dispatch_allowed": True,
            "handoff_path": "handoffs/T-CODEX-H1__composer__to__claude.md",
            "errors": [],
            "worktree_required": True,
            "base_sha": BASE_SHA,
            "approval_gate": {"approval_level": "human", "approval_status": "pending_human"},
            "risk_gate": {"approval_level": "high", "risk_level": "high"},
            "plan_path": "runtime/orchestrator/latest_plan.json",
        }
        base.update(overrides)
        return base

    def _allocation_record(self, preview: dict) -> dict:
        wt_root, wt_path = self._worktree_paths()
        return {
            "allocation_id": "alloc-codex-h1",
            "task_id": preview["task_id"],
            "run_id": preview["run_id"],
            "base_sha": preview["base_sha"],
            "status": "active",
            "worktree_root": str(wt_root.resolve()),
            "worktree_path": str(wt_path.resolve()),
        }

    def _signed_human_approval(self, preview: dict, adapter: dict) -> dict:
        command = str(preview["command"])
        cmd_hash = hashlib.sha256(command.encode("utf-8")).hexdigest()
        preview_hash = compute_preview_hash(preview, adapter=adapter)
        unsigned = build_unsigned_signed_record(
            approval_id="approval-codex-h1-001",
            task_id=preview["task_id"],
            run_id=preview["run_id"],
            preview_id=preview["run_id"],
            preview_hash=preview_hash,
            adapter_id=preview["adapter_id"],
            approval_level="human",
            approver_type="human",
            approved_by="human-operator-h1",
            allowed_command_hash=cmd_hash,
            allowed_cwd=str(preview["working_directory"]),
            allowed_scope_paths=list(preview["scope_paths"]),
            nonce="codex-h1-nonce",
        )
        unsigned["approved_at"] = unsigned["issued_at"]
        unsigned["scope"] = "dispatch_execution"
        signed = sign_approval_record(unsigned, approver_type="human")
        assert signed.success, signed.errors
        assert signed.record is not None
        return signed.record

    def _cli_inventory(self) -> dict:
        return yaml.safe_load(
            (self.root / "runtime/registry/cli_inventory.yaml").read_text(encoding="utf-8")
        )

    def _write_phase3_7b_authorization(self, activation_id: str = "activation-h1-fixture") -> Path:
        act_dir = self.root / "runtime" / "dispatch" / "codex_activation" / activation_id
        act_dir.mkdir(parents=True, exist_ok=True)
        auth = {
            "authorized": True,
            "human_authorization_reference": "human-ref-h1-fixture",
            "recorded_at": "2026-06-29T12:00:00Z",
        }
        path = act_dir / "phase3_7b_authorization.json"
        path.write_text(json.dumps(auth, indent=2), encoding="utf-8")
        return path


class GenericExecutorBypassTests(CodexH1FixtureMixin, unittest.TestCase):
    def test_generic_blocks_codex_with_valid_human_approval(self) -> None:
        preview = self._codex_preview()
        adapter = self._codex_adapter()
        allocation = self._allocation_record(preview)
        approval = self._signed_human_approval(preview, adapter)
        wt_path = Path(preview["working_directory"])
        marker = wt_path / "pre-exec-marker.txt"
        marker.write_text("unchanged\n", encoding="utf-8")

        gate = evaluate_execution_gates(
            self.root,
            preview,
            adapter=adapter,
            cli_inventory=self._cli_inventory(),
            approval_record=approval,
            operator_execute=True,
            dry_run=False,
            allocation_record=allocation,
            worktree_root=str(allocation["worktree_path"]),
            check_replay=True,
            execution_route=ROUTE_GENERIC_DISPATCH,
        )
        non_route = [
            r
            for r in gate.blocked_reasons
            if DEDICATED_CANARY_RUNNER_REASON not in r
        ]
        self.assertIn(DEDICATED_CANARY_RUNNER_REASON, gate.blocked_reasons)
        self.assertFalse(gate.execution_allowed)
        self.assertFalse(gate.execution_route_allowed)
        self.assertEqual(gate.execution_route_required, ROUTE_CODEX_LOCAL_BUILDER)
        self.assertEqual(non_route, [], gate.blocked_reasons)

        preview_path = self.root / "runtime" / "preview_codex_h1.json"
        preview_path.write_text(json.dumps(preview, indent=2), encoding="utf-8")
        approval_path = self.root / "runtime" / "approval_codex_h1.json"
        approval_path.write_text(json.dumps(approval, indent=2), encoding="utf-8")
        allocation_path = self.root / "runtime" / "allocation_codex_h1.json"
        allocation_path.write_text(json.dumps(allocation, indent=2), encoding="utf-8")

        with patch("dispatch.executor.subprocess.run") as mock_run, patch(
            "dispatch.executor.try_claim_approval"
        ) as mock_claim:
            result = execute_dispatch(
                self.root,
                preview_path,
                operator_execute=True,
                dry_run=False,
                approval_path=approval_path,
                allocation_path=allocation_path,
            )
            mock_run.assert_not_called()
            mock_claim.assert_not_called()

        self.assertFalse(result.executed)
        self.assertFalse(result.execution_allowed)
        self.assertIn(DEDICATED_CANARY_RUNNER_REASON, result.blocked_reasons)
        self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged\n")

    def test_generic_blocks_even_with_phase3_7b_authorization(self) -> None:
        self._write_phase3_7b_authorization()
        preview = self._codex_preview()
        adapter = self._codex_adapter()
        allocation = self._allocation_record(preview)
        approval = self._signed_human_approval(preview, adapter)

        gate = evaluate_execution_gates(
            self.root,
            preview,
            adapter=adapter,
            cli_inventory=self._cli_inventory(),
            approval_record=approval,
            operator_execute=True,
            dry_run=False,
            allocation_record=allocation,
            worktree_root=str(allocation["worktree_path"]),
            execution_route=ROUTE_GENERIC_DISPATCH,
        )
        self.assertFalse(gate.execution_allowed)
        self.assertIn(DEDICATED_CANARY_RUNNER_REASON, gate.blocked_reasons)

        preview_path = self.root / "runtime" / "preview_codex_h1.json"
        preview_path.write_text(json.dumps(preview, indent=2), encoding="utf-8")
        approval_path = self.root / "runtime" / "approval_codex_h1.json"
        approval_path.write_text(json.dumps(approval, indent=2), encoding="utf-8")
        allocation_path = self.root / "runtime" / "allocation_codex_h1.json"
        allocation_path.write_text(json.dumps(allocation, indent=2), encoding="utf-8")

        with patch("dispatch.executor.subprocess.run") as mock_run, patch(
            "dispatch.executor.try_claim_approval"
        ) as mock_claim:
            result = execute_dispatch(
                self.root,
                preview_path,
                operator_execute=True,
                dry_run=False,
                approval_path=approval_path,
                allocation_path=allocation_path,
            )
            mock_run.assert_not_called()
            mock_claim.assert_not_called()
        self.assertFalse(result.executed)
        self.assertIn(DEDICATED_CANARY_RUNNER_REASON, result.blocked_reasons)

    def test_execute_dispatch_cli_cannot_bypass(self) -> None:
        preview = self._codex_preview()
        adapter = self._codex_adapter()
        allocation = self._allocation_record(preview)
        approval = self._signed_human_approval(preview, adapter)
        preview_path = self.root / "runtime" / "preview_codex_h1.json"
        preview_path.write_text(json.dumps(preview, indent=2), encoding="utf-8")
        approval_path = self.root / "runtime" / "approval_codex_h1.json"
        approval_path.write_text(json.dumps(approval, indent=2), encoding="utf-8")
        allocation_path = self.root / "runtime" / "allocation_codex_h1.json"
        allocation_path.write_text(json.dumps(allocation, indent=2), encoding="utf-8")

        completed = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "execute_dispatch.py"),
                "--root",
                str(self.root),
                "--preview",
                str(preview_path),
                "--execute",
                "--approval",
                str(approval_path),
                "--allocation",
                str(allocation_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(REPO_ROOT),
        )

        self.assertNotEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload.get("executed"))
        self.assertFalse(payload.get("execution_allowed"))
        blocked = payload.get("blocked_reasons") or payload.get("route_block_reasons") or []
        joined = " ".join(blocked)
        self.assertIn("dedicated canary runner", joined.lower())

    def test_no_approval_claim_on_route_block(self) -> None:
        preview = self._codex_preview()
        adapter = self._codex_adapter()
        approval = self._signed_human_approval(preview, adapter)
        preview_path = self.root / "runtime" / "preview_codex_h1.json"
        preview_path.write_text(json.dumps(preview, indent=2), encoding="utf-8")
        approval_path = self.root / "runtime" / "approval_codex_h1.json"
        approval_path.write_text(json.dumps(approval, indent=2), encoding="utf-8")

        with patch("dispatch.approval_replay.try_claim_approval") as mock_claim:
            result = execute_dispatch(
                self.root,
                preview_path,
                operator_execute=True,
                dry_run=False,
                approval_path=approval_path,
            )
            mock_claim.assert_not_called()
        self.assertFalse(result.executed)
        self.assertIn(DEDICATED_CANARY_RUNNER_REASON, result.blocked_reasons)


class CanaryRoutePolicyTests(CodexH1FixtureMixin, unittest.TestCase):
    def test_local_builder_route_allowed(self) -> None:
        dedicated = load_codex_restricted_adapter(REPO_ROOT)
        route = evaluate_execution_route(dedicated, ROUTE_CODEX_LOCAL_BUILDER)
        self.assertTrue(route.allowed, route.reasons)

    def test_canary_route_blocked_for_local_worktree_adapter(self) -> None:
        dedicated = load_codex_restricted_adapter(REPO_ROOT)
        route = evaluate_execution_route(dedicated, ROUTE_CODEX_CANARY)
        self.assertFalse(route.allowed, route.reasons)

    def test_activation_gates_still_block_canary_runner(self) -> None:
        canary_adapter = _canary_fixture_adapter()

        registry_adapter = self._codex_adapter()
        with patch("subprocess.run") as mock_run:
            gate = evaluate_activation_gates(
                REPO_ROOT,
                registry_adapter=registry_adapter,
                dedicated_adapter=canary_adapter,
                execute_flag=True,
                require_phase3_7b=True,
            )
            mock_run.assert_not_called()

        self.assertFalse(gate.allowed)
        self.assertTrue(gate.gate_results.get("execution_route"))
        self.assertIn(PHASE3_7B_BLOCKED_REASON, gate.blocked_reasons)

    def test_wrong_routes_block(self) -> None:
        codex = self._codex_adapter()
        local = _local_adapter()

        generic_codex = evaluate_execution_route(codex, ROUTE_GENERIC_DISPATCH)
        self.assertFalse(generic_codex.allowed)

        canary_local = evaluate_execution_route(local, ROUTE_CODEX_CANARY)
        self.assertFalse(canary_local.allowed)

        unknown = evaluate_execution_route(codex, "mcp_execution")
        self.assertFalse(unknown.allowed)

        preview_exec = evaluate_execution_route(codex, ROUTE_PREVIEW_ONLY)
        self.assertTrue(preview_exec.allowed)

    def test_local_fixture_still_generic_executable(self) -> None:
        task_dir = self.root / "tasks" / "active"
        task_dir.mkdir(parents=True, exist_ok=True)
        task = {
            "id": "T-EXEC",
            "title": "Executor test",
            "owner": "composer",
            "reviewer": "claude",
            "created_by": "composer",
            "status": "ready",
            "phase": "3.2",
            "created_at": "2026-06-12T12:00:00Z",
            "updated_at": "2026-06-12T12:00:00Z",
            "priority": "low",
            "risk_level": "low",
            "requires_human_approval": False,
            "human_approval_checklist": [],
            "objective": "Run safe python test",
            "context": "test",
            "goals": [],
            "non_goals": [],
            "inputs": [],
            "outputs": [],
            "constraints": [],
            "acceptance": [],
            "notes": "",
        }
        (task_dir / "T-EXEC.yaml").write_text(yaml.safe_dump(task, sort_keys=False), encoding="utf-8")
        orch = self.root / "runtime" / "orchestrator"
        orch.mkdir(parents=True, exist_ok=True)
        plan = {
            "run_id": "run-exec",
            "task_id": "T-EXEC",
            "recommended_primary_agent": "composer",
            "recommended_reviewer": "claude",
            "approval_level": "none",
            "approval_required": False,
            "files_to_inspect": [],
        }
        (orch / "latest_plan.json").write_text(json.dumps(plan), encoding="utf-8")
        state = {
            "run_id": "run-exec",
            "task_id": "T-EXEC",
            "task_path": "tasks/active/T-EXEC.yaml",
            "plan_path": "runtime/orchestrator/latest_plan.json",
            "approval_level": "none",
            "risk_level": "low",
        }
        (orch / "latest_state.json").write_text(json.dumps(state), encoding="utf-8")
        inv_dir = self.root / "runtime" / "registry"
        inv_dir.mkdir(parents=True, exist_ok=True)
        (inv_dir / "cli_inventory.yaml").write_text(
            yaml.safe_dump(
                {"tools": [{"name": "python", "available": True, "path": sys.executable}]},
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        preview = build_dispatch_preview(self.root, adapter_id="local-python-exec-test")
        paths = persist_preview(self.root, preview)
        preview_path = self.root / paths["preview_path"]

        mock_completed = subprocess.CompletedProcess(
            args=["python", "-c", "print('agentic-os-executor-test')"],
            returncode=0,
            stdout="agentic-os-executor-test\n",
            stderr="",
        )
        with patch("dispatch.executor.subprocess.run", return_value=mock_completed) as mock_run:
            result = execute_dispatch(
                self.root,
                preview_path,
                operator_execute=True,
                dry_run=False,
            )
            mock_run.assert_called_once()
        self.assertTrue(result.executed)
        self.assertTrue(result.execution_allowed)


class PolicyMutationTests(unittest.TestCase):
    def _base_codex_policy(self) -> dict:
        return {
            "id": "codex-restricted",
            "execution_scope": "local_worktree",
            "dedicated_runner_required": True,
            "required_execution_route": ROUTE_CODEX_LOCAL_BUILDER,
            "phase3_7b_authorization_required": False,
            "promotion_state": "restricted_execution",
            "supports_execution": True,
            "maximum_runs": 0,
        }

    def test_policy_mutations_fail_validation_or_block(self) -> None:
        cases = [
            ("dedicated_runner_required", False),
            ("required_execution_route", ROUTE_GENERIC_DISPATCH),
            ("required_execution_route", ""),
            ("execution_scope", "general"),
            ("phase3_7b_authorization_required", True),
        ]
        for field, bad_value in cases:
            adapter = self._base_codex_policy()
            adapter[field] = bad_value
            contradictions = validate_adapter_route_policy(adapter)
            route = evaluate_execution_route(adapter, ROUTE_GENERIC_DISPATCH)
            self.assertTrue(
                contradictions or not route.allowed,
                f"expected block for {field}={bad_value!r}",
            )

    def test_phase3_7b_fixture_does_not_open_generic_route(self) -> None:
        adapter = self._base_codex_policy()
        route = evaluate_execution_route(adapter, ROUTE_GENERIC_DISPATCH)
        self.assertFalse(route.allowed)
        self.assertIn(DEDICATED_CANARY_RUNNER_REASON, route.reasons)


if __name__ == "__main__":
    unittest.main()