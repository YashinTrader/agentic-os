#!/usr/bin/env python3
"""Persistent physical agent supervisor entrypoint (execution layer).

Consumes wake records, claims assignments, launches real agent processes
(Grok primary / Codex fallback), and records PID/run state.

On process end, completion routing:
  1) outbox + assignment → awaiting_review
  2) structured poke to orchestrator only (notification layer)

Pokes are never launch evidence. PID/run records are never completion evidence.
This is NOT the passive watcher — claim alone is never reported as a launch.
Keep this process running for the autonomous loop's execution layer.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from orchestrator.supervisor import SupervisorConfig, process_once, run_forever  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Physical agent supervisor (Grok primary, Codex fallback)")
    parser.add_argument("--root", default=str(REPO_ROOT), help="Repository root")
    parser.add_argument("--agent", default="composer", help="Wake queue agent id")
    parser.add_argument("--once", action="store_true", help="Process at most one wake and exit")
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--max-turns", type=int, default=30)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--worktree", default=None, help="Optional fixed worktree path")
    parser.add_argument("--grok-executable", default=None)
    parser.add_argument("--codex-executable", default=None)
    parser.add_argument("--no-codex-fallback", action="store_true")
    parser.add_argument("--json", action="store_true", help="Always print JSON (default for --once)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    config = SupervisorConfig(
        agent=args.agent,
        poll_seconds=max(1, args.poll_seconds),
        max_turns=args.max_turns,
        timeout_seconds=args.timeout_seconds,
        worktree=args.worktree,
        grok_executable=args.grok_executable,
        codex_executable=args.codex_executable,
        allow_codex_fallback=not args.no_codex_fallback,
    )

    if args.once:
        report = process_once(root, config=config)
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        status = report.get("status")
        return 0 if status in {"idle", "completed", "skipped", "deferred", "blocked"} else 1

    return run_forever(root, config=config)


if __name__ == "__main__":
    raise SystemExit(main())
