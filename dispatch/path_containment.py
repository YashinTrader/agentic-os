"""Path containment helpers for dispatch worktree and cwd policies."""

from __future__ import annotations

import os
from pathlib import Path


def path_is_inside(candidate: Path, allowed_root: Path, *, allow_equal: bool = True) -> bool:
    """Return True when candidate resolves inside allowed_root (no string prefix checks)."""
    try:
        root = allowed_root.resolve(strict=False)
        resolved = candidate.resolve(strict=False)
    except OSError:
        return False

    if os.name == "nt":
        try:
            if resolved.drive.lower() != root.drive.lower():
                return False
        except AttributeError:
            pass

    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return False

    if not allow_equal and relative == Path("."):
        return False

    if ".." in relative.parts:
        return False

    if _symlink_escapes_root(candidate, root):
        return False

    return True


def _symlink_escapes_root(candidate: Path, allowed_root: Path) -> bool:
    """Detect symlink hops that resolve outside allowed_root when possible."""
    current = candidate
    seen: set[Path] = set()
    while True:
        try:
            if current.is_symlink():
                target = current.readlink()
                if not target.is_absolute():
                    target = (current.parent / target).resolve(strict=False)
                else:
                    target = target.resolve(strict=False)
                if target in seen:
                    return True
                seen.add(target)
                if not path_is_inside(target, allowed_root, allow_equal=True):
                    return True
                current = target
                continue
        except OSError:
            return True
        break
    return False