#!/usr/bin/env python3
"""Create a Phase 1 task YAML file in tasks/active/."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Create a task YAML file in tasks/active/.")
    p.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
    p.add_argument("--id", required=True, help="Task id, for example T-0012.")
    p.add_argument("--title", required=True, help="Task title.")
    p.add_argument("--owner", default="codex", help="Responsible agent. Defaults to codex.")
    p.add_argument("--status", default="todo", choices=["todo", "in_progress", "review", "blocked", "done"])
    p.add_argument("--objective", required=True, help="Task objective.")
    p.add_argument("--input", action="append", dest="inputs", default=[], help="Input path. Repeatable.")
    p.add_argument("--output", action="append", dest="outputs", default=[], help="Output path. Repeatable.")
    p.add_argument("--constraint", action="append", dest="constraints", default=[], help="Constraint. Repeatable.")
    p.add_argument("--acceptance", action="append", dest="acceptance", default=[], help="Acceptance criterion. Repeatable.")
    p.add_argument("--handoff-notes", default="Hand off with a summary of work completed and verification results.")
    p.add_argument("--risk-level", default="low", choices=["low", "medium", "high"])
    p.add_argument("--requires-human-approval", action="store_true")
    p.add_argument("--priority", default="P1")
    p.add_argument("--depends-on", action="append", default=[])
    p.add_argument("--blocks", action="append", default=[])
    p.add_argument("--label", action="append", dest="labels", default=[])
    p.add_argument("--estimated-effort", default="S")
    p.add_argument("--related-decision", action="append", dest="related_decisions", default=[])
    p.add_argument("--force", action="store_true", help="Overwrite an existing task file.")
    return p


def main() -> int:
    args = parser().parse_args()
    root = Path(args.root).resolve()
    task_path = root / "tasks" / "active" / f"{args.id}.yaml"
    if task_path.exists() and not args.force:
        print(f"{task_path.relative_to(root)} already exists; use --force to overwrite", file=sys.stderr)
        return 1

    now = utc_now()
    task = {
        "id": args.id,
        "title": args.title,
        "owner": args.owner,
        "status": args.status,
        "created": now,
        "updated": now,
        "objective": args.objective,
        "inputs": args.inputs or ["README.md"],
        "outputs": args.outputs or [f"tasks/active/{args.id}.yaml"],
        "constraints": args.constraints or ["Follow the existing Agentic OS protocols."],
        "acceptance_criteria": args.acceptance or ["Task file validates with scripts/validate.py."],
        "handoff_notes": args.handoff_notes,
        "risk_level": args.risk_level,
        "requires_human_approval": bool(args.requires_human_approval),
        "priority": args.priority,
        "depends_on": args.depends_on,
        "blocks": args.blocks,
        "labels": args.labels,
        "estimated_effort": args.estimated_effort,
        "related_decisions": args.related_decisions,
    }

    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(yaml.safe_dump(task, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(task_path.relative_to(root).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
