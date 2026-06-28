from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.execution_gate import adapter_supports_execution  # noqa: E402


PHASE_3_4_MODULES = (
    "dispatch/worktree_allocator.py",
    "dispatch/worktree_registry.py",
    "dispatch/approval_signing.py",
    "dispatch/approval_replay.py",
    "dispatch/execution_gate.py",
)


class Phase34SafetyBoundaryTests(unittest.TestCase):
    def test_only_local_python_exec_test_supports_execution(self) -> None:
        registry = yaml.safe_load(
            (REPO_ROOT / "agents" / "adapter_registry.yaml").read_text(encoding="utf-8")
        )
        execution_capable: list[str] = []
        for adapter in registry["adapters"]:
            if adapter.get("supports_execution"):
                execution_capable.append(adapter["id"])
            else:
                self.assertFalse(adapter_supports_execution(adapter), adapter["id"])

        self.assertEqual(execution_capable, ["local-python-exec-test"])

    def test_phase34_modules_never_use_shell_true(self) -> None:
        for rel in PHASE_3_4_MODULES:
            path = REPO_ROOT / rel
            self.assertTrue(path.exists(), rel)
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("shell=True", source, rel)
            if "subprocess.run" in source:
                self.assertIn("shell=False", source, rel)

    def test_dashboard_has_no_execute_controls(self) -> None:
        source = (REPO_ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
        dispatch_section = source[source.find("TAB PANEL: DISPATCH") : source.find("TAB PANEL: HEALTH")]
        for forbidden in ("Execute button", "Approve button", "Launch agent", "Run MCP"):
            self.assertNotIn(forbidden, dispatch_section)
        self.assertIn("Read-only", dispatch_section)
        self.assertNotIn('type="submit"', dispatch_section)


if __name__ == "__main__":
    unittest.main()