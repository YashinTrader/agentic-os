#!/usr/bin/env python3
"""Persistent physical agent supervisor entrypoint.

Consumes wake records, claims assignments, launches real agent processes
(Grok primary / Codex fallback), records PID/run state, and routes completion
to awaiting_review with Claude-only pokes.

This is NOT the passive watcher — claim alone is never reported as a launch.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from orchestrator.supervisor import SupervisorConfig, process_once, run_forever  # noqa: E402
from orchestrator.rotating_log import RotatingLogWriter  # noqa: E402


from scripts.state_root import resolve_state_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Physical agent supervisor (Grok primary, Codex fallback)")
    parser.add_argument("--state-root", default=None)
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
    parser.add_argument("--log-path", default=None)
    args = parser.parse_args()

    try:
        root = resolve_state_root(args.root, args.state_root)
    except ValueError as exc:
        parser.error(str(exc))
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

    log = RotatingLogWriter(Path(args.log_path) if args.log_path else root / "logs/supervisor.jsonl", max_bytes=10 * 1024 * 1024, backups=5)
    return run_forever(root, config=config, state_logger=log.log_json)


if __name__ == "__main__":
    raise SystemExit(main())
