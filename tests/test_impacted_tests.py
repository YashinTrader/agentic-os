"""Static selection avoids missing package imports and patch-only dependencies."""
from pathlib import Path
import tempfile
import unittest

from scripts.impacted_tests import impacted_tests, module_name, references


class ImpactedTestsTests(unittest.TestCase):
    def test_imports_and_patch_targets(self):
        refs = references('''import orchestrator.supervisor as supervisor
from dispatch import worktree_allocator
from orchestrator.quota_probe import probe
@mock.patch("orchestrator.process_ownership.owned_run")
def test_probe(): pass
patch(target="orchestrator.agent_launcher.owned_popen")
''')
        self.assertTrue({"orchestrator.supervisor", "dispatch.worktree_allocator",
                         "orchestrator.quota_probe", "orchestrator.process_ownership.owned_run",
                         "orchestrator.agent_launcher.owned_popen"} <= refs)

    def test_selection_is_sorted_and_matches_module_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            for name, source in {
                "test_a": 'from dispatch import worktree_allocator',
                "test_b": 'patch("dispatch.worktree_allocator.run_git")',
                "test_c": 'import dispatch.worktree_allocator_extra',
                "test_changed": '',
            }.items():
                (root / "tests" / f"{name}.py").write_text(source)
            self.assertEqual(impacted_tests(root, ["dispatch/worktree_allocator.py",
                                                   "tests/test_changed.py", "docs/x.md"]),
                             ["tests.test_a", "tests.test_b", "tests.test_changed"])
        self.assertEqual(module_name("dispatch/__init__.py"), "dispatch")
