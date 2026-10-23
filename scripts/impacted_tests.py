#!/usr/bin/env python3
"""List direct static test dependents of Python modules changed in a Git range.

Imports (including from-package imports) and literal patch targets are checked.
This is a direct dependency selector, not a transitive dependency analysis.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import subprocess


def module_name(path: str) -> str | None:
    if not path.endswith(".py"):
        return None
    parts = path.replace("\\", "/")[:-3].split("/")
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def references(source: str) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
            result.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call):
            func = node.func
            is_patch = (isinstance(func, ast.Name) and func.id == "patch") or (
                isinstance(func, ast.Attribute) and func.attr == "patch")
            if is_patch:
                targets = list(node.args[:1]) + [kw.value for kw in node.keywords if kw.arg == "target"]
                result.update(target.value for target in targets
                              if isinstance(target, ast.Constant) and isinstance(target.value, str))
    return result


def impacted_tests(root: Path, changed_paths: list[str]) -> list[str]:
    changed = {name for path in changed_paths if (name := module_name(path))}
    selected = []
    for path in sorted((root / "tests").rglob("test_*.py")):
        name = module_name(path.relative_to(root).as_posix())
        refs = references(path.read_text(encoding="utf-8-sig"))
        if name in changed or any(ref == mod or ref.startswith(mod + ".")
                                  for ref in refs for mod in changed):
            selected.append(name)
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Base ref, or a complete Git range")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    revision = args.base if ".." in args.base else f"{args.base}..{args.head}"
    proc = subprocess.run(["git", "diff", "--name-only", "-z", revision, "--"],
                          cwd=args.root, capture_output=True, text=True, check=True)
    for name in impacted_tests(args.root, proc.stdout.split("\0")):
        print(name)
    return 0


if __name__ == "__main__":
    if __package__:
        from ._console import configure_console
    else:
        from _console import configure_console
    configure_console()
    raise SystemExit(main())
