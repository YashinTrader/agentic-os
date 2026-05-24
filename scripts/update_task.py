#!/usr/bin/env python3
"""Update a task YAML file and move it to the directory matching its status."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


STATE_DIRS = {
    "ready": "active",
    "todo": "active",
    "in_progress": "active",
    "review": "active",
    "blocked": "blocked",
    "done": "done",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def find_task(root: Path, task_id: str) -> Path | None:
    for state_dir in ("active", "done", "blocked"):
        path = root / "tasks" / state_dir / f"{task_id}.yaml"
        if path.exists():
            return path
    return None


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Update a task YAML file.")
    p.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
    p.add_argument("--id", required=True, help="Task id to update.")
    p.add_argument("--status", choices=sorted(STATE_DIRS), help="New task status.")
    p.add_argument("--owner", help="New task owner.")
    p.add_argument("--reviewer", help="New task reviewer.")
    p.add_argument("--title", help="New task title.")
    p.add_argument("--risk-level", choices=["low", "medium", "high"], help="New risk level.")
    p.add_argument("--handoff-notes", dest="notes", help="Replacement notes.")
    return p


def main() -> int:
    args = parser().parse_args()
    root = Path(args.root).resolve()
    current_path = find_task(root, args.id)
    if current_path is None:
        print(f"Task {args.id} not found", file=sys.stderr)
        return 1

    task = yaml.safe_load(current_path.read_text(encoding="utf-8"))
    if not isinstance(task, dict):
        print(f"{current_path.relative_to(root)} is not a YAML mapping", file=sys.stderr)
        return 1

    for key, value in (
        ("status", args.status),
        ("owner", args.owner),
        ("reviewer", args.reviewer),
        ("title", args.title),
        ("risk_level", args.risk_level),
        ("notes", args.notes),
    ):
        if value is not None:
            task[key] = "ready" if key == "status" and value == "todo" else value

    status = task.get("status", "ready")
    owner = task.get("owner")
    reviewer = task.get("reviewer")
    if status in {"review", "done"} and not reviewer:
        print("reviewer is required when status is review or done", file=sys.stderr)
        return 1
    if reviewer and owner == reviewer:
        print("reviewer must differ from owner", file=sys.stderr)
        return 1

    task["updated_at"] = utc_now()
    task.pop("updated", None)

    target_dir = STATE_DIRS[status]
    target_path = root / "tasks" / target_dir / current_path.name
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(yaml.safe_dump(task, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    if target_path != current_path:
        current_path.unlink()

    print(target_path.relative_to(root).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
