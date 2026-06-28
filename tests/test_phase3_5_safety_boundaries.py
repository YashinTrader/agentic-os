from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

PHASE_3_5_MODULES = (
    "dispatch/codex_adapter.py",
    "dispatch/agent_environment.py",
    "dispatch/agent_context_bundle.py",
    "dispatch/agent_result_parser.py",
    "scripts/inspect_codex_cli.py",
    "scripts/preview_codex_dispatch.py",
    "scripts/run_codex_canary.py",
)


class Phase35SafetyBoundaryTests(unittest.TestCase):
    def test_phase35_modules_never_use_shell_true(self) -> None:
        for rel in PHASE_3_5_MODULES:
            path = REPO_ROOT / rel
            self.assertTrue(path.exists(), rel)
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("shell=True", source, rel)
            if "subprocess.run" in source or "subprocess.Popen" in source:
                self.assertIn("shell=False", source, rel)

    def test_inspect_codex_cli_fixed_argv_only(self) -> None:
        source = (REPO_ROOT / "scripts" / "inspect_codex_cli.py").read_text(encoding="utf-8")
        self.assertIn("FIXED_INVOCATIONS", source)
        self.assertNotIn("os.system", source)
        self.assertNotIn("os.popen", source)

    def test_codex_adapter_has_no_subprocess(self) -> None:
        source = (REPO_ROOT / "dispatch" / "codex_adapter.py").read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("subprocess.run", source)


if __name__ == "__main__":
    unittest.main()