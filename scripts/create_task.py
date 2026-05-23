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


STATUS_MAP = {"todo": "ready"}
PRIORITY_MAP = {"P0": "high", "P1": "high", "P2": "medium", "P3": "low"}


def reviewer_for(owner: str, requested: str | None = None) -> str:
    reviewer = requested or "claude"
    if reviewer == owner:
        return "codex" if owner != "codex" else "claude"
    return reviewer


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Create a task YAML file in tasks/active/.")
    p.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
    p.add_argument("--id", required=True, help="Task id, for example T-0012.")
    p.add_argument("--title", required=True, help="Task title.")
    p.add_argument("--owner", default="codex", help="Responsible agent. Defaults to codex.")
    p.add_argument("--reviewer", help="Reviewer agent. Defaults to claude, unless owner is claude.")
    p.add_argument("--created-by", help="Creator agent. Defaults to owner.")
    p.add_argument("--phase", default="1.5", help="Project phase. Defaults to 1.5.")
    p.add_argument("--status", default="ready", choices=["ready", "todo", "in_progress", "review", "blocked", "done"])
    p.add_argument("--objective", required=True, help="Task objective.")
    p.add_argument("--context", help="Longer-form context. Defaults to objective.")
    p.add_argument("--goal", action="append", dest="goals", default=[], help="Goal. Repeatable.")
    p.add_argument("--non-goal", action="append", dest="non_goals", default=[], help="Non-goal. Repeatable.")
    p.add_argument("--input", action="append", dest="inputs", default=[], help="Input path. Repeatable.")
    p.add_argument("--output", action="append", dest="outputs", default=[], help="Output path. Repeatable.")
    p.add_argument("--constraint", action="append", dest="constraints", default=[], help="Constraint. Repeatable.")
    p.add_argument("--acceptance", action="append", dest="acceptance", default=[], help="Acceptance criterion. Repeatable.")
    p.add_argument("--handoff-notes", default="Hand off with a summary of work completed and verification results.")
    p.add_argument("--approval-check", action="append", dest="approval_checks", default=[], help="Human approval checklist item. Repeatable.")
    p.add_argument("--risk-level", default="low", choices=["low", "medium", "high"])
    p.add_argument("--requires-human-approval", action="store_true")
    p.add_argument("--priority", default="high")
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
    status = STATUS_MAP.get(args.status, args.status)
    priority = PRIORITY_MAP.get(args.priority, args.priority)
    approval_checks = list(args.approval_checks)
    if args.requires_human_approval and not approval_checks:
        approval_checks.append("Human confirms this task may proceed.")
    task = {
        "id": args.id,
        "title": args.title,
        "status": status,
        "owner": args.owner,
        "reviewer": reviewer_for(args.owner, args.reviewer),
        "created_by": args.created_by or args.owner,
        "created_at": now,
        "updated_at": now,
        "phase": args.phase,
        "priority": priority,
        "risk_level": args.risk_level,
        "requires_human_approval": bool(args.requires_human_approval),
        "depends_on": args.depends_on,
        "blocks": args.blocks,
        "labels": args.labels,
        "estimated_effort": args.estimated_effort,
        "related_decisions": args.related_decisions,
        "objective": args.objective,
        "context": args.context or args.objective,
        "goals": args.goals or [args.objective],
        "non_goals": args.non_goals,
        "inputs": args.inputs or ["README.md"],
        "outputs": args.outputs or [f"tasks/active/{args.id}.yaml"],
        "constraints": args.constraints or ["Follow the existing Agentic OS protocols."],
        "acceptance": args.acceptance or ["Task file validates with scripts/validate.py."],
        "human_approval_checklist": approval_checks,
        "notes": args.handoff_notes,
    }

    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(yaml.safe_dump(task, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(task_path.relative_to(root).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
