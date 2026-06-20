#!/usr/bin/env python3
"""Phase 3.2 controlled dispatch executor — operator-commanded only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.executor import execute_dispatch  # noqa: E402
from dispatch.runtime_capture import ExecutionResult  # noqa: E402


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Controlled dispatch executor (Phase 3.2). Requires explicit --dry-run or --execute."
    )
    p.add_argument("--root", default=str(REPO_ROOT), help="Repository root.")
    p.add_argument("--preview", required=True, help="Path to dispatch preview JSON.")
    p.add_argument("--dry-run", action="store_true", help="Validate gates and write artifacts without subprocess.")
    p.add_argument("--execute", action="store_true", help="Execute command after all gates pass (narrow allowlist).")
    p.add_argument("--approval", help="Path to approval record JSON (required when approval level needs it).")
    p.add_argument("--worktree-root", help="Optional approved worktree root for file-writing execution.")
    p.add_argument("--allocation", help="Path to worktree allocation record JSON.")
    p.add_argument("--allocation-id", help="Worktree allocation_id (loads runtime record).")
    return p


def main() -> int:
    args = parser().parse_args()
    root = Path(args.root).resolve()
    preview_path = Path(args.preview)
    if not preview_path.is_absolute():
        preview_path = (root / preview_path).resolve()

    if not args.dry_run and not args.execute:
        print("error: must pass --dry-run or --execute", file=sys.stderr)
        return 2

    if args.dry_run and args.execute:
        print("error: cannot combine --dry-run and --execute", file=sys.stderr)
        return 2

    approval_path = None
    if args.approval:
        approval_path = Path(args.approval)
        if not approval_path.is_absolute():
            approval_path = (root / approval_path).resolve()

    allocation_path = None
    if args.allocation:
        allocation_path = Path(args.allocation)
        if not allocation_path.is_absolute():
            allocation_path = (root / allocation_path).resolve()

    try:
        result = execute_dispatch(
            root,
            preview_path,
            operator_execute=args.execute,
            dry_run=args.dry_run,
            approval_path=approval_path,
            worktree_root=args.worktree_root,
            allocation_path=allocation_path,
            allocation_id=args.allocation_id,
        )
    except Exception as exc:
        print(f"execute failed: {exc}", file=sys.stderr)
        return 1

    payload = _result_to_dict(result)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if result.event_emit_errors:
        print("warning: event emission failures recorded in result.event_emit_errors", file=sys.stderr)
        for err in result.event_emit_errors:
            print(f"  - {err}", file=sys.stderr)
    if not result.execution_allowed:
        return 3
    if args.dry_run:
        return 0
    if result.timed_out or (result.exit_code is not None and result.exit_code != 0):
        return 4
    return 0


def _result_to_dict(result: ExecutionResult) -> dict:
    from dataclasses import asdict

    return asdict(result)


if __name__ == "__main__":
    raise SystemExit(main())