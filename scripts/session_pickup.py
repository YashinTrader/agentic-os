#!/usr/bin/env python3
"""Grok Build session start: list pending assignments and claim the first one.

Run at the start of every Grok session so Claude-posted work is picked up without
Gabriel (or human) relaying. Pure file ops — no network.

Usage:
  python scripts/session_pickup.py           # claim first pending (if any)
  python scripts/session_pickup.py --list    # list only
  python scripts/session_pickup.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.assignment_channel import (  # noqa: E402
    claim_assignment,
    format_assignment_contract,
    list_pending_assignments,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Session start: list/claim pending Claude→Grok assignments."
    )
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--list", action="store_true", help="List pending only; do not claim")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--claimed-by",
        default="composer",
        help="Claimant identity (default: composer)",
    )
    args = parser.parse_args()
    root = Path(args.root).resolve()

    pending, errors = list_pending_assignments(root)
    if args.list or not pending:
        if args.json:
            print(
                json.dumps(
                    {
                        "pending_count": len(pending),
                        "pending": [
                            {
                                "assignment_id": r.assignment_id,
                                "task_id": r.task_id,
                                "title": r.title,
                                "status": r.status,
                            }
                            for r in pending
                        ],
                        "warnings": errors,
                    },
                    indent=2,
                )
            )
        else:
            if not pending:
                print("No pending assignments.")
            else:
                print(f"{len(pending)} pending assignment(s):")
                for r in pending:
                    print(f"  {r.assignment_id}\t{r.task_id}\t{r.title}")
            if not args.list and not pending:
                print("Idle — nothing to claim. Claude posts via scripts/assignments.py create.")
        return 0

    first = pending[0]
    if not args.json:
        print(f"Claiming first pending: {first.assignment_id} ({first.task_id})")
    record, claim_errors = claim_assignment(
        root, first.assignment_id, claimed_by=args.claimed_by
    )
    errors.extend(claim_errors)
    if record is None:
        for e in errors:
            print(e, file=sys.stderr)
        return 1

    if args.json:
        from dispatch.assignment_channel import assignment_to_payload

        print(
            json.dumps(
                {
                    "status": "claimed",
                    "assignment": assignment_to_payload(record),
                    "warnings": errors,
                },
                indent=2,
            )
        )
    else:
        print(f"CLAIMED {record.assignment_id}")
        print()
        print(format_assignment_contract(record), end="")
        print()
        print("Next: build on new_branch, run gates, then:")
        print(
            f"  python scripts/assignments.py complete {record.assignment_id} "
            f"--handoff {record.handoff_path} --branch {record.new_branch} "
            f"--branch-tip-sha <40-char-sha> --summary '…'"
        )
        print("Claude then: python scripts/assignments.py ingest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
