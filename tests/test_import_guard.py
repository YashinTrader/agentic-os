"""Every application module must import successfully in a fresh interpreter."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ImportGuardTests(unittest.TestCase):
    def test_modules_import_in_fresh_interpreters(self):
        paths = sorted(
            path
            for folder in ("orchestrator", "dispatch", "scripts")
            for path in (ROOT / folder).rglob("*.py")
            if "__pycache__" not in path.parts
            and (folder != "scripts" or path.parent == ROOT / folder)
        )
        for path in paths:
            relative = path.relative_to(ROOT).with_suffix("")
            parts = relative.parts
            module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
            with self.subTest(module=module):
                result = subprocess.run(
                    [sys.executable, "-c", "import importlib; importlib.import_module(" + repr(module) + ")"],
                    cwd=ROOT, capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
