import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ConsoleEncodingTests(unittest.TestCase):
    def test_list_tasks_cp1252(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for state in ("active", "done", "blocked"):
                folder = root / "tasks" / state
                folder.mkdir(parents=True)
                title = "Unicode \u2192 title \u2014 preserved"
                (folder / "task.yaml").write_text(
                    f"id: T-{state}\ntitle: {title}\n", encoding="utf-8"
                )
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/list_tasks.py"), "--root", str(root)],
                env={**os.environ, "PYTHONIOENCODING": "cp1252"},
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("cp1252"))
            for state in ("active", "done", "blocked"):
                self.assertIn(f"T-{state}", result.stdout.decode("cp1252"))
                self.assertIn(title, (root / "tasks" / state / "task.yaml").read_text(encoding="utf-8"))

    def test_helper_handles_both_streams_and_capture(self):
        import io
        from unittest.mock import patch
        from scripts._console import configure_console

        out_bytes, err_bytes = io.BytesIO(), io.BytesIO()
        out = io.TextIOWrapper(out_bytes, encoding="cp1252")
        err = io.TextIOWrapper(err_bytes, encoding="cp1252")
        with patch.object(sys, "stdout", out), patch.object(sys, "stderr", err):
            configure_console()
            print("\u2192", flush=True)
            print("\u2192", file=sys.stderr, flush=True)
        self.assertEqual(out_bytes.getvalue().strip(), b"?")
        self.assertEqual(err_bytes.getvalue().strip(), b"?")
        with patch.object(sys, "stdout", io.StringIO()), patch.object(sys, "stderr", io.StringIO()):
            configure_console()

    def test_printing_entrypoints_configure_console_before_main(self):
        import ast
        for path in (ROOT / "scripts").glob("*.py"):
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source)
            if "print(" not in source:
                continue
            for node in tree.body:
                if isinstance(node, ast.If) and "__name__" in ast.unparse(node.test):
                    calls = [ast.unparse(item) for item in node.body]
                    self.assertIn("configure_console()", calls, path.name)
                    self.assertLess(calls.index("configure_console()"), len(calls) - 1, path.name)

