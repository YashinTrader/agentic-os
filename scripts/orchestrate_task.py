#!/usr/bin/env python3
"""Run LangGraph orchestration planning for a task (no agent execution)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from orchestrator.graph import run_orchestration  # noqa: E402
from orchestrator.loaders import safe_task_path  # noqa: E402


def resolve_output_dir(
    repo_root: Path,
    output_dir: str | None,
    *,
    allow_outside_repo: bool = False,
) -> str:
    """Resolve orchestrator output directory inside repo root by default."""
    default = repo_root / "runtime" / "orchestrator" / "runs"
    if output_dir is None:
        return str(default.resolve())

    candidate = Path(output_dir)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (repo_root / candidate).resolve()

    if ".." in candidate.parts:
        raise ValueError(
            f"output directory must not contain path traversal segments: {output_dir}"
        )

    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        if not allow_outside_repo:
            raise ValueError(
                f"output directory must be inside repository root ({repo_root}); "
                f"got {resolved}. Pass --allow-outside-repo only for explicit override."
            ) from exc

    return str(resolved)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Plan orchestration for a task using LangGraph.")
    p.add_argument("--root", default=str(REPO_ROOT), help="Repository root.")
    p.add_argument("--task", required=True, help="Path to task YAML under tasks/.")
    p.add_argument("--json", action="store_true", help="Output full state JSON.")
    p.add_argument("--dry-run", action="store_true", help="Plan without writing runtime files or logs.")
    p.add_argument("--no-log", action="store_true", help="Skip appending orchestration event to logs.")
    p.add_argument(
        "--output-dir",
        default=None,
        help="Override output runs directory (default: runtime/orchestrator/runs; must stay inside repo).",
    )
    p.add_argument(
        "--allow-outside-repo",
        action="store_true",
        help="Explicit unsafe override to allow --output-dir outside repository root.",
    )
    return p


def main() -> int:
    args = parser().parse_args()
    root = Path(args.root).resolve()

    try:
        safe_task_path(root, args.task)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        resolved_output = resolve_output_dir(root, args.output_dir, allow_outside_repo=args.allow_outside_repo)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        state = run_orchestration(
            root,
            args.task,
            dry_run=args.dry_run,
            no_log=args.no_log,
            output_dir=resolved_output,
        )
    except ImportError as exc:
        print(str(exc), file=sys.stderr)
        print("Install LangGraph: pip install -r requirements.txt", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"orchestration failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(state.to_json())
        return 1 if state.errors else 0

    print("Orchestration plan generated (not executed)")
    print(f"  Run ID:          {state.run_id}")
    print(f"  Task:            {state.task_id}")
    print(f"  Selected team:   {state.selected_team} (score {state.selected_team_score})")
    print(f"  Primary agent:   {state.recommended_primary_agent}")
    print(f"  Reviewer:        {state.recommended_reviewer}")
    print(f"  Approval:        {state.approval_level} (required={state.approval_required})")
    print(f"  Next action:     {state.next_action}")
    if state.context_pack_path:
        print(f"  Context pack:    {state.context_pack_path}")
    if state.plan_path:
        print(f"  Plan:            {state.plan_path}")
    if state.warnings:
        print("  Warnings:")
        for w in state.warnings:
            print(f"    - {w}")
    if state.errors:
        print("  Errors:")
        for e in state.errors:
            print(f"    - {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())