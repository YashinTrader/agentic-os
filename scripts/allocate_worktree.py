#!/usr/bin/env python3
"""Operator-commanded worktree allocation (Phase 3.4)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.worktree_allocator import allocate_worktree  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Allocate a Git worktree for a task run")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--base-branch", default="")
    parser.add_argument("--owner", default="operator")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    result = allocate_worktree(
        root,
        task_id=args.task_id,
        run_id=args.run_id,
        base_sha=args.base_sha,
        base_branch=args.base_branch,
        owner=args.owner,
    )
    payload = {
        "success": result.success,
        "worktree_path": result.worktree_path,
        "branch_name": result.branch_name,
        "allocation_id": result.record.allocation_id if result.record else None,
        "errors": result.errors,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())