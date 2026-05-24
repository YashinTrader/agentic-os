#!/usr/bin/env python3
"""Append one ADR-0004 event to logs/agent-events.jsonl."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ALLOWED_EVENT_TYPES = {
    "task_created",
    "task_assigned",
    "status_changed",
    "handoff_written",
    "reviewed",
    "decision_recorded",
    "blocked",
    "note",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Append one JSONL event to logs/agent-events.jsonl.")
    p.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
    p.add_argument("--ts", help="UTC timestamp. Defaults to current time.")
    p.add_argument("--agent", required=True)
    p.add_argument("--task", dest="task_id", help="Task id. Backward-compatible alias for --task-id.")
    p.add_argument("--task-id", dest="task_id")
    p.add_argument("--type", dest="event_type")
    p.add_argument("--event", dest="event_type", help="Deprecated alias for --type.")
    p.add_argument("--detail")
    p.add_argument("--text")
    p.add_argument("--ref")
    p.add_argument("--force", action="store_true", help="Allow an unknown event type with a warning.")
    return p


def main() -> int:
    args = parser().parse_args()
    if not args.event_type:
        print("--type is required", file=sys.stderr)
        return 1
    if args.event_type not in ALLOWED_EVENT_TYPES:
        if not args.force:
            print(f"unknown event type {args.event_type!r}; pass --force to append anyway", file=sys.stderr)
            return 1
        print(f"Warning: appending unknown event type {args.event_type!r}", file=sys.stderr)

    root = Path(args.root).resolve()
    event = {
        "ts": args.ts or utc_now(),
        "agent": args.agent,
        "type": args.event_type,
    }
    if args.task_id:
        event["task_id"] = args.task_id
    if args.detail:
        event["detail"] = args.detail
    if args.text:
        event["text"] = args.text
    if args.ref:
        event["ref"] = args.ref

    log_path = root / "logs" / "agent-events.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(log_path.relative_to(root).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
