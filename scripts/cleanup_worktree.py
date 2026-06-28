#!/usr/bin/env python3
"""Conservative worktree cleanup (Phase 3.4)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.worktree_allocator import cleanup_worktree  # noqa: E402
from dispatch.worktree_registry import allocation_record_to_dict  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup worktree allocation")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--allocation", required=True, help="allocation_id")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    result = cleanup_worktree(root, args.allocation)
    payload = {
        "success": result.success,
        "errors": result.errors,
        "record": allocation_record_to_dict(result.record) if result.record else None,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())