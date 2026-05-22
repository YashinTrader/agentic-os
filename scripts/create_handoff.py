#!/usr/bin/env python3
"""Create a protocol-compliant handoff Markdown file."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def bullets(items: list[str]) -> str:
    values = items or ["None."]
    return "\n".join(f"- {item}" for item in values)


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
    path = root / "handoffs" / f"{args.task}__{args.from_agent}__to__{args.to_agent}.md"
    if path.exists() and not args.force:
        print(f"{path.relative_to(root)} already exists; use --force to overwrite", file=sys.stderr)
        return 1

    text = f"""# Handoff: {args.task}
**From:** {args.from_agent}
**To:** {args.to_agent}
**Date:** {args.date or utc_now()}
**Task Status After Handoff:** {args.status}

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
"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(path.relative_to(root).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
