from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.path_containment import path_is_inside  # noqa: E402


class PathContainmentTests(unittest.TestCase):
    def test_child_inside_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "safe"
            root.mkdir()
            child = root / "child"
            child.mkdir()
            self.assertTrue(path_is_inside(child, root))

    def test_root_equal_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.assertTrue(path_is_inside(root, root))

    def test_sibling_prefix_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            safe = Path(tmp) / "safe"
            evil = Path(tmp) / "safe-evil"
            safe.mkdir()
            evil.mkdir()
            self.assertFalse(path_is_inside(evil, safe))

    def test_traversal_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            traversal = root / ".." / "outside"
            self.assertFalse(path_is_inside(traversal.resolve(strict=False), root))

    def test_absolute_outside_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            outside = Path(tmp).resolve().parent
            self.assertFalse(path_is_inside(outside, root))


if __name__ == "__main__":
    unittest.main()