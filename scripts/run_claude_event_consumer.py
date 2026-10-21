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
from orchestrator.layer_heartbeat import install_stop_handlers
from orchestrator.rotating_log import RotatingLogWriter


from scripts.state_root import resolve_state_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Persistent headless Claude event consumer")
    parser.add_argument("--state-root", default=None)
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--log-path", default=None)
    args = parser.parse_args()
    try:
        root = resolve_state_root(args.root, args.state_root)
    except ValueError as exc:
        parser.error(str(exc))
    log = RotatingLogWriter(Path(args.log_path) if args.log_path else root / "logs/claude-event-consumer.jsonl", max_bytes=10 * 1024 * 1024, backups=5)
    consumer = ClaudeEventConsumer(root, state_logger=log.log_json)
    if args.once:
        report = consumer.process_once()
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report.get("status") in {"idle", "resolved", "deduplicated", "deferred"} else 1
    install_stop_handlers()
    return consumer.run_forever(poll_seconds=args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
