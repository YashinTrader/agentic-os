#!/usr/bin/env python3
"""Consume local wake signals and claim matching file-channel assignments."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.agent_wake import read_wake_signal  # noqa: E402
from dispatch.assignment_channel import claim_assignment  # noqa: E402


def process_one(repo_root: Path, agent: str) -> dict:
    queue = repo_root / "runtime" / "dispatch" / "wake_queue" / agent
    signals = sorted(queue.glob("*.json")) if queue.is_dir() else []
    if not signals:
        return {"status": "idle", "agent": agent}
    path = signals[0]
    signal = read_wake_signal(path)
    record, errors = claim_assignment(repo_root, signal["assignment_id"], claimed_by=agent)
    if record is None:
        return {"status": "pending", "assignment_id": signal["assignment_id"], "errors": errors}
    consumed = repo_root / "runtime" / "dispatch" / "wake_queue" / "consumed" / path.name
    consumed.parent.mkdir(parents=True, exist_ok=True)
    path.replace(consumed)
    return {"status": "claimed", "assignment_id": record.assignment_id, "task_id": record.task_id, "agent": agent}


def main() -> int:
    parser = argparse.ArgumentParser(description="Local assignment wake watcher")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--agent", default="composer")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=5)
    args = parser.parse_args()
    while True:
        report = process_one(Path(args.root).resolve(), args.agent)
        print(json.dumps(report, sort_keys=True), flush=True)
        if args.once:
            return 0 if report["status"] in {"idle", "claimed"} else 1
        time.sleep(max(1, args.poll_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
