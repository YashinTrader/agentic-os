"""Every application module imports independently in one fresh interpreter."""
import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPORT_BATCH = r'''
import importlib
import json
import os
from pathlib import Path
import sys
import traceback

root = os.path.normcase(str(Path.cwd().resolve())) + os.sep
modules = json.loads(sys.argv[1])
failures = {}
for module in modules:
    # Keep third-party imports warm, but never retain application modules.
    for name, loaded in list(sys.modules.items()):
        filename = getattr(loaded, "__file__", None)
        if name.split(".")[0] in {"orchestrator", "dispatch", "scripts"} or (
            filename and os.path.normcase(os.path.abspath(filename)).startswith(root)
        ):
            del sys.modules[name]
    importlib.invalidate_caches()
    try:
        importlib.import_module(module)
    except BaseException:
        failures[module] = traceback.format_exc()
print(json.dumps(failures))
sys.exit(bool(failures))
'''


def run_import_batch(root, modules):
    return subprocess.run(
        [sys.executable, "-c", IMPORT_BATCH, json.dumps(modules)],
        cwd=root, capture_output=True, text=True,
    )


class ImportGuardTests(unittest.TestCase):
    def test_modules_import_in_fresh_interpreters(self):
        paths = sorted(
            path
            for folder in ("orchestrator", "dispatch", "scripts")
            for path in (ROOT / folder).rglob("*.py")
            if "__pycache__" not in path.parts
            and (folder != "scripts" or path.parent == ROOT / folder)
        )
        modules = []
        for path in paths:
            parts = path.relative_to(ROOT).with_suffix("").parts
            modules.append(".".join(parts[:-1] if parts[-1] == "__init__" else parts))
        # T-M1-19: loaders must work before any dispatch module warms its imports.
        modules.remove("orchestrator.loaders")
        modules.insert(0, "orchestrator.loaders")
        started = time.monotonic()
        result = run_import_batch(ROOT, modules)
        elapsed = time.monotonic() - started
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertLess(elapsed, 60, f"Import batch took {elapsed:.1f}s")
