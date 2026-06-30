from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_activation_gate import (  # noqa: E402
    evaluate_activation_gates,
    evaluate_post_canary_suspension,
    phase3_7b_authorization_path,
)
from dispatch.codex_canary_gates import evaluate_canary_execution_gates  # noqa: E402
from dispatch.preview import get_adapter_by_id, load_adapter_registry  # noqa: E402


class Phase37aSafetyBoundaryTests(unittest.TestCase):
    ACTIVATION = "activation-disable-test"

    def test_phase3_7b_authorization_absent(self) -> None:
        path = phase3_7b_authorization_path(REPO_ROOT, self.ACTIVATION)
        self.assertFalse(path.exists())

    def test_emergency_disable_blocks(self) -> None:
        subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "disable_codex_canary.py"),
                "--activation",
                self.ACTIVATION,
                "--reason",
                "test disable",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
            cwd=str(REPO_ROOT),
        )
        registry = load_adapter_registry(REPO_ROOT)
        adapter = get_adapter_by_id(registry, "codex-restricted") or {}
        result = evaluate_activation_gates(
            REPO_ROOT,
            registry_adapter=adapter,
            execute_flag=True,
            activation_id=self.ACTIVATION,
        )
        self.assertFalse(result.allowed)
        self.assertTrue(any("emergency disable" in r for r in result.blocked_reasons))

    def test_post_canary_suspension_one_attempt(self) -> None:
        state = evaluate_post_canary_suspension(
            runs_consumed=1, maximum_runs=1, attempt_status="completed"
        )
        self.assertTrue(state["second_attempt_blocked"])
        self.assertFalse(state["automatic_retry_allowed"])
        self.assertEqual(state["status_after_attempt"], "suspended_pending_review")

    def test_gates_never_invoke_subprocess(self) -> None:
        registry = load_adapter_registry(REPO_ROOT)
        adapter = get_adapter_by_id(registry, "codex-restricted") or {}
        with mock.patch("subprocess.run") as run_mock:
            evaluate_canary_execution_gates(REPO_ROOT, registry_adapter=adapter, execute_flag=True)
            run_mock.assert_not_called()

    def test_no_real_human_approval_in_repo(self) -> None:
        for path in REPO_ROOT.rglob("human_approval.json"):
            if "runtime" in path.parts:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertNotIn("signature", data)


if __name__ == "__main__":
    unittest.main()