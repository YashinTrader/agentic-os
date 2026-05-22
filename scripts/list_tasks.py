#!/usr/bin/env python3
"""List task YAML files across active, done, and blocked directories."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="List tasks from tasks/active, tasks/done, and tasks/blocked.")
    p.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
    p.add_argument("--state", choices=["all", "active", "done", "blocked"], default="all")
    return p


def load_task(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a YAML mapping")
    return data


def main() -> int:
    args = parser().parse_args()
    root = Path(args.root).resolve()
    states = ["active", "done", "blocked"] if args.state == "all" else [args.state]
    rows: list[tuple[str, str, str, str, str]] = []

    for state in states:
        for path in sorted((root / "tasks" / state).glob("*.yaml")):
            try:
                task = load_task(path)
            except Exception as exc:
                print(f"Skipping {path.relative_to(root)}: {exc}", file=sys.stderr)
                continue
            rows.append(
                (
                    state,
                    str(task.get("id", path.stem)),
                    str(task.get("status", "")),
                    str(task.get("owner", "")),
                    str(task.get("title", "")),
                )
            )

    print("state    id        status       owner   title")
    print("-------  --------  -----------  ------  -----")
    for state, task_id, status, owner, title in rows:
        print(f"{state:<7}  {task_id:<8}  {status:<11}  {owner:<6}  {title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
