#!/usr/bin/env python3
"""Create a protocol-compliant handoff Markdown file."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


V2_HEADER_FIELDS = {"id", "title", "status", "owner", "reviewer", "created_by", "created_at", "updated_at", "phase"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def bullets(items: list[str]) -> str:
    values = items or ["None."]
    return "\n".join(f"- {item}" for item in values)


def find_task(root: Path, task_id: str) -> Path | None:
    for state_dir in ("active", "done", "blocked"):
        path = root / "tasks" / state_dir / f"{task_id}.yaml"
        if path.exists():
            return path
    return None


def validate_task_header(root: Path, task_id: str) -> str | None:
    path = find_task(root, task_id)
    if path is None:
        return f"Task {task_id} not found"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return f"{path.relative_to(root)} is not a YAML mapping"
    missing = sorted(V2_HEADER_FIELDS - set(data))
    if missing:
        return f"{path.relative_to(root)} missing v2 header fields: {', '.join(missing)}"
    if data.get("owner") == data.get("reviewer"):
        return f"{path.relative_to(root)} reviewer must differ from owner"
    return None


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Create a handoff Markdown file.")
    p.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
    p.add_argument("--task", required=True, help="Task id.")
    p.add_argument("--from-agent", required=True)
    p.add_argument("--to-agent", required=True)
    p.add_argument("--status", default="review")
    p.add_argument("--date", help="UTC timestamp. Defaults to current time.")
    p.add_argument("--what-i-did", action="append", default=[])
    p.add_argument("--what-remains", action="append", default=[])
    p.add_argument("--decision", action="append", default=[])
    p.add_argument("--open-question", action="append", default=[])
    p.add_argument("--verify", action="append", default=[])
    p.add_argument("--risk", action="append", default=[])
    p.add_argument("--next-action", action="append", default=[])
    p.add_argument("--force", action="store_true", help="Overwrite an existing handoff.")
    return p


def main() -> int:
    args = parser().parse_args()
    root = Path(args.root).resolve()
    header_error = validate_task_header(root, args.task)
    if header_error:
        print(header_error, file=sys.stderr)
        return 1

    path = root / "handoffs" / f"{args.task}__{args.from_agent}__to__{args.to_agent}.md"
    if path.exists() and not args.force:
        print(f"{path.relative_to(root)} already exists; use --force to overwrite", file=sys.stderr)
        return 1

    text = f"""# Handoff: {args.task}
**From:** {args.from_agent}
**To:** {args.to_agent}
**Date:** {args.date or utc_now()}
**Task Status After Handoff:** {args.status}
**Handoff Protocol:** v2

## What I Did
{bullets(args.what_i_did)}

## What Remains
{bullets(args.what_remains)}

## Decisions Made
{bullets(args.decision)}

## Open Questions
{bullets(args.open_question)}

## How to Verify My Work
{bullets(args.verify)}

## Risks / Caveats
{bullets(args.risk)}

## Recommended Next Action for Receiver
{bullets(args.next_action)}

## Repository Verification

repo_root: REPLACE_WITH_GIT_TOPLEVEL
branch: REPLACE_WITH_BRANCH
base_sha: REPLACE_WITH_40_CHAR_BASE_SHA
implementation_sha: REPLACE_WITH_40_CHAR_IMPLEMENTATION_SHA
tests_commit_sha: REPLACE_WITH_40_CHAR_TESTS_COMMIT_SHA
final_head_sha: REPLACE_WITH_40_CHAR_FINAL_HEAD_SHA
remote_head_sha: REPLACE_WITH_40_CHAR_REMOTE_HEAD_SHA
git_status_clean: false
validator_commit_sha: REPLACE_WITH_40_CHAR_VALIDATOR_COMMIT_SHA
test_count: REPLACE_WITH_DISCOVERED_TEST_COUNT
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: none
working_copy_path: REPLACE_WITH_CANONICAL_CLONE_PATH

<!-- Generate the block with: python scripts/handoff_verification_block.py --base-sha ... -->
"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    print(path.relative_to(root).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
