#!/usr/bin/env python3
"""Dedicated Codex local-builder runner — standing policy, no per-run approval."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_local_builder import run_local_builder  # noqa: E402
from orchestrator.loaders import resolve_task_path  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Codex local builder for one task.")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--task", required=True, help="Task YAML path under tasks/")
    parser.add_argument("--base-sha", default="", help="Optional base commit SHA")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    task_path = resolve_task_path(root, args.task)
    result = run_local_builder(
        root,
        task_path=task_path,
        base_sha=args.base_sha or None,
    )

    payload = {
        "run_id": result.run_id,
        "task_id": result.task_id,
        "status": result.status,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "worktree_path": result.worktree_path,
        "allocation_id": result.allocation_id,
        "handoff_path": result.handoff_path,
        "changed_files": result.changed_files,
        "blocked_reasons": result.blocked_reasons,
        "run_dir": result.run_dir,
        "codex_subprocess_invoked": result.codex_subprocess_invoked,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2))

    if result.status == "completed_verified":
        return 0
    if result.status in {"completed_unverified", "blocked"}:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())