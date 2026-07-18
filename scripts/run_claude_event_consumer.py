#!/usr/bin/env python3
"""Run the persistent Claude terminal-poke consumer."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from orchestrator.claude_event_consumer import ClaudeEventConsumer


def main() -> int:
    parser = argparse.ArgumentParser(description="Persistent headless Claude event consumer")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    args = parser.parse_args()
    consumer = ClaudeEventConsumer(Path(args.root).resolve())
    if args.once:
        report = consumer.process_once()
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report.get("status") in {"idle", "resolved", "deduplicated", "deferred"} else 1
    return consumer.run_forever(poll_seconds=args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
