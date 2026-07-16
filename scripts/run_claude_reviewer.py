#!/usr/bin/env python3
"""One-shot or polling Claude Code headless reviewer (logical orchestrator)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from orchestrator.claude_reviewer_adapter import AUTH_MODE_API, AUTH_MODE_LOCAL, ClaudeReviewerAdapter  # noqa: E402
from orchestrator.review_dispatcher import process_one_review  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Headless Claude reviewer for awaiting_review assignments")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--assignment-id", default=None)
    parser.add_argument("--once", action="store_true", default=True)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--review-concurrency", type=int, default=1)
    parser.add_argument("--auth-mode", choices=[AUTH_MODE_LOCAL, AUTH_MODE_API], default=AUTH_MODE_LOCAL)
    parser.add_argument("--claude-executable", default=None)
    parser.add_argument("--no-apply", action="store_true", help="Collect verdict without mutating assignment state")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    adapter = ClaudeReviewerAdapter(
        root,
        claude_executable=args.claude_executable,
        auth_mode=args.auth_mode,
    )
    report = process_one_review(
        root,
        assignment_id=args.assignment_id,
        adapter=adapter,
        review_concurrency=args.review_concurrency,
        timeout_seconds=args.timeout_seconds,
        apply=not args.no_apply,
    )
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    status = report.get("status")
    return 0 if status in {"idle", "completed", "skipped", "deferred"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
