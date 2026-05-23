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


RENAMES = {
    "created": "created_at",
    "updated": "updated_at",
    "acceptance_criteria": "acceptance",
    "handoff_notes": "notes",
}
STATUS_MAP = {"todo": "ready"}
PRIORITY_MAP = {"P0": "high", "P1": "high", "P2": "medium", "P3": "low"}


def reviewer_for(owner: str, requested: str | None = None) -> str:
    reviewer = requested or "claude"
    if reviewer == owner:
        return "codex" if owner != "codex" else "claude"
    return reviewer


def normalize_task(task: dict, task_id: str) -> dict:
    normalized = dict(task)
    for old, new in RENAMES.items():
        if old in normalized and new not in normalized:
            normalized[new] = normalized.pop(old)
    if normalized.get("status") in STATUS_MAP:
        normalized["status"] = STATUS_MAP[normalized["status"]]
    if normalized.get("priority") in PRIORITY_MAP:
        normalized["priority"] = PRIORITY_MAP[normalized["priority"]]
    owner = normalized.get("owner", "codex")
    normalized.setdefault("reviewer", reviewer_for(owner))
    normalized.setdefault("created_by", owner)
    normalized.setdefault("phase", "1.5")
    normalized.setdefault("priority", "high")
    normalized.setdefault("context", normalized.get("objective", ""))
    normalized.setdefault("goals", [normalized.get("objective", "")] if normalized.get("objective") else [])
    normalized.setdefault("non_goals", [])
    normalized.setdefault("human_approval_checklist", [])
    normalized.setdefault("outputs", [f"tasks/active/{task_id}.yaml"])
    normalized.setdefault("constraints", ["Follow the existing Agentic OS protocols."])
    normalized.setdefault("acceptance", ["Task file validates with scripts/validate.py."])
    normalized.setdefault("notes", "Hand off with a summary of work completed and verification results.")
    return normalized


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
    p.add_argument("--reviewer", help="New reviewer.")
    p.add_argument("--title", help="New task title.")
    p.add_argument("--risk-level", choices=["low", "medium", "high"], help="New risk level.")
    p.add_argument("--handoff-notes", help="Replacement handoff notes.")
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

    task = normalize_task(task, args.id)

    for key, value in (
        ("status", args.status),
        ("owner", args.owner),
        ("reviewer", args.reviewer),
        ("title", args.title),
        ("risk_level", args.risk_level),
        ("notes", args.handoff_notes),
    ):
        if value is not None:
            task[key] = STATUS_MAP.get(value, value) if key == "status" else value
    task["reviewer"] = reviewer_for(task.get("owner", "codex"), task.get("reviewer"))
    task["updated_at"] = utc_now()

    target_dir = STATE_DIRS[task.get("status", "todo")]
    target_path = root / "tasks" / target_dir / current_path.name
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(yaml.safe_dump(task, sort_keys=False, allow_unicode=True), encoding="utf-8")
    if target_path != current_path:
        current_path.unlink()

    print(target_path.relative_to(root).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
