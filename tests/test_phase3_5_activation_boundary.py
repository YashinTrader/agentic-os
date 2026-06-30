from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.execution_gate import adapter_supports_execution  # noqa: E402


class ActivationBoundaryTests(unittest.TestCase):
    def test_execution_capable_adapters_bounded(self) -> None:
        registry = yaml.safe_load(
            (REPO_ROOT / "agents" / "adapter_registry.yaml").read_text(encoding="utf-8")
        )
        capable = [a["id"] for a in registry["adapters"] if adapter_supports_execution(a)]
        self.assertEqual(sorted(capable), ["codex-restricted", "local-python-exec-test"])

    def test_codex_restricted_activation_candidate(self) -> None:
        entry = next(
            a for a in yaml.safe_load(
                (REPO_ROOT / "agents" / "adapter_registry.yaml").read_text(encoding="utf-8")
            )["adapters"]
            if a["id"] == "codex-restricted"
        )
        self.assertEqual(entry["promotion_state"], "activation_candidate")
        self.assertTrue(entry["supports_execution"])
        self.assertEqual(entry.get("execution_scope"), "canary_only")

    def test_canary_script_refuses_without_activation(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "run_codex_canary.py")],
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(completed.returncode, 3)
        self.assertIn("refused", completed.stdout.lower())


if __name__ == "__main__":
    unittest.main()