from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_activation import build_activation_manifest_v2  # noqa: E402
from dispatch.codex_activation_gate import PHASE3_7B_BLOCKED_REASON  # noqa: E402
from dispatch.codex_canary_gates import evaluate_canary_execution_gates  # noqa: E402


class Phase37aNoLiveExecutionTests(unittest.TestCase):
    REVIEWED = "d9f203c39c3a85613ef4c7f76e110e3f4734d9c1"

    def _registry_adapter(self) -> dict:
        registry = yaml.safe_load(
            (REPO_ROOT / "agents" / "adapter_registry.yaml").read_text(encoding="utf-8")
        )
        return next(a for a in registry["adapters"] if a["id"] == "codex-restricted")

    def test_runner_refuses_without_phase3_7b(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "run_codex_canary.py"),
                "--execute-canary",
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(completed.returncode, 3)
        report = json.loads(completed.stdout)
        self.assertEqual(report["status"], "refused")
        self.assertFalse(report["codex_subprocess_invoked"])
        self.assertFalse(report["approval_consumed"])
        self.assertIn(PHASE3_7B_BLOCKED_REASON, report["blocked_reasons"])

    def test_fake_approval_alone_refuses(self) -> None:
        manifest = build_activation_manifest_v2(
            REPO_ROOT,
            activation_id="activation-fake-approval",
            reviewed_commit_sha=self.REVIEWED,
            cli_version="0.136.0",
            cli_help_hash="fixture",
            status="human_approved",
        )
        approval = {
            "adapter_id": "codex-restricted",
            "signature": "fake-signature",
            "consumed": False,
        }
        allocation = {"allocation_id": "alloc-1", "worktree_path": "/tmp/wt"}
        compat = {
            "version_raw": "0.136.0",
            "executable_path": "/bin/codex",
            "help_hash": "fixture",
            "invocations": [],
            "compatible": True,
        }
        with mock.patch("subprocess.run") as run_mock:
            result = evaluate_canary_execution_gates(
                REPO_ROOT,
                registry_adapter=self._registry_adapter(),
                execute_flag=True,
                activation_manifest=manifest,
                human_approval=approval,
                allocation_record=allocation,
                cli_compatibility=compat,
                reviewed_sha=self.REVIEWED,
            )
            run_mock.assert_not_called()
        self.assertFalse(result.allowed)
        self.assertIn(PHASE3_7B_BLOCKED_REASON, result.blocked_reasons)

    def test_supports_execution_alone_insufficient(self) -> None:
        with mock.patch("subprocess.run") as run_mock:
            result = evaluate_canary_execution_gates(
                REPO_ROOT,
                registry_adapter=self._registry_adapter(),
                execute_flag=False,
            )
            run_mock.assert_not_called()
        self.assertFalse(result.allowed)

    def test_runner_source_has_no_subprocess_run(self) -> None:
        source = (REPO_ROOT / "scripts" / "run_codex_canary.py").read_text(encoding="utf-8")
        self.assertNotIn("subprocess.run", source)


if __name__ == "__main__":
    unittest.main()