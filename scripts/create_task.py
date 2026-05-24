#!/usr/bin/env python3
"""Create a schema-v2 task YAML file in tasks/active/."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


RISKY_OUTPUT_PREFIXES = ("scripts/", "docs/", "decisions/")
PRIORITY_MAP = {"P0": "high", "P1": "high", "P2": "medium", "P3": "low"}
STATUS_MAP = {"todo": "ready"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Create a task YAML file in tasks/active/.")
    p.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
    p.add_argument("--id", required=True, help="Task id, for example T-0012.")
    p.add_argument("--title", required=True, help="Task title.")
    p.add_argument("--owner", default="codex", help="Responsible agent. Defaults to codex.")
    p.add_argument("--reviewer", required=True, help="Reviewer agent. Must differ from owner.")
    p.add_argument("--created-by", help="Task author. Defaults to owner.")
    p.add_argument("--phase", default="1.5", help="Task phase. Defaults to 1.5.")
    p.add_argument("--status", default="ready", choices=["ready", "todo", "in_progress", "review", "blocked", "done"])
    p.add_argument("--objective", required=True, help="Task objective.")
    p.add_argument("--context", help="Longer task context. Defaults to objective.")
    p.add_argument("--goal", action="append", dest="goals", default=[], help="Goal. Repeatable.")
    p.add_argument("--non-goal", action="append", dest="non_goals", default=[], help="Non-goal. Repeatable.")
    p.add_argument("--input", action="append", dest="inputs", default=[], help="Input path. Repeatable.")
    p.add_argument("--output", action="append", dest="outputs", default=[], help="Output path. Repeatable.")
    p.add_argument("--constraint", action="append", dest="constraints", default=[], help="Constraint. Repeatable.")
    p.add_argument("--acceptance", action="append", dest="acceptance", default=[], help="Acceptance criterion. Repeatable.")
    p.add_argument("--handoff-notes", dest="notes", default="Hand off with a summary of work completed and verification results.")
    p.add_argument("--risk-level", default="low", choices=["low", "medium", "high"])
    p.add_argument("--requires-human-approval", action="store_true")
    p.add_argument("--human-approval-checklist-item", action="append", default=[])
    p.add_argument("--priority", default="high")
    p.add_argument("--depends-on", action="append", default=[])
    p.add_argument("--blocks", action="append", default=[])
    p.add_argument("--label", action="append", dest="labels", default=[])
    p.add_argument("--estimated-effort", default="S")
    p.add_argument("--related-decision", action="append", dest="related_decisions", default=[])
    p.add_argument("--force", action="store_true", help="Overwrite an existing task file.")
    return p


def normalize_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def touches_risky_surface(outputs: list[str]) -> bool:
    for output in outputs:
        normalized = normalize_path(output)
        if normalized == "requirements.txt" or normalized.startswith(RISKY_OUTPUT_PREFIXES):
            return True
    return False


def normalized_priority(value: str) -> str:
    return PRIORITY_MAP.get(value, value)


def main() -> int:
    args = parser().parse_args()
    if args.owner == args.reviewer:
        print("reviewer must differ from owner", file=sys.stderr)
        return 1

    root = Path(args.root).resolve()
    task_path = root / "tasks" / "active" / f"{args.id}.yaml"
    if task_path.exists() and not args.force:
        print(f"{task_path.relative_to(root)} already exists; use --force to overwrite", file=sys.stderr)
        return 1

    outputs = args.outputs or [f"tasks/active/{args.id}.yaml"]
    risky = touches_risky_surface(outputs)
    risk_level = "medium" if risky and args.risk_level == "low" else args.risk_level
    requires_human_approval = bool(args.requires_human_approval or risky)
    checklist = args.human_approval_checklist_item
    if requires_human_approval and not checklist:
        print("human approval checklist item is required for human-approved or risky tasks", file=sys.stderr)
        return 1

    now = utc_now()
    status = STATUS_MAP.get(args.status, args.status)
    objective = args.objective
    task = {
        "id": args.id,
        "title": args.title,
        "status": status,
        "owner": args.owner,
        "reviewer": args.reviewer,
        "created_by": args.created_by or args.owner,
        "created_at": now,
        "updated_at": now,
        "phase": args.phase,
        "priority": normalized_priority(args.priority),
        "risk_level": risk_level,
        "requires_human_approval": requires_human_approval,
        "depends_on": args.depends_on,
        "blocks": args.blocks,
        "labels": args.labels,
        "estimated_effort": args.estimated_effort,
        "related_decisions": args.related_decisions,
        "objective": objective,
        "context": args.context or objective,
        "goals": args.goals or [objective],
        "non_goals": args.non_goals,
        "inputs": args.inputs or ["README.md"],
        "outputs": outputs,
        "constraints": args.constraints or ["Follow the existing Agentic OS protocols."],
        "acceptance": args.acceptance or ["Task file validates with scripts/validate.py."],
        "human_approval_checklist": checklist,
        "notes": args.notes,
    }

    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(yaml.safe_dump(task, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    print(task_path.relative_to(root).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
