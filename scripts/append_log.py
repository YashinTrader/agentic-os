#!/usr/bin/env python3
"""Append one event to logs/agent-events.jsonl."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Append one JSONL event to logs/agent-events.jsonl.")
    p.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
    p.add_argument("--ts", help="UTC timestamp. Defaults to current time.")
    p.add_argument("--agent", required=True)
    p.add_argument("--task", required=True)
    p.add_argument("--event", required=True)
    p.add_argument("--detail")
    p.add_argument("--ref")
    return p


def main() -> int:
    args = parser().parse_args()
    root = Path(args.root).resolve()
    event = {
        "ts": args.ts or utc_now(),
        "agent": args.agent,
        "task": args.task,
        "event": args.event,
    }
    if args.detail:
        event["detail"] = args.detail
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
