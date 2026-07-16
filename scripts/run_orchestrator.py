#!/usr/bin/env python3
"""Persistent physical supervisor: builders + Claude reviewer.

Execution layer:
  - consume builder wakes, launch Grok/Codex
  - for awaiting_review, launch headless Claude Code reviewer

Notification layer remains separate (orchestrator pokes).

Preferred:
  python scripts/run_orchestrator.py --agents composer,codex,claude-reviewer --poll-seconds 5
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from orchestrator.claude_reviewer_adapter import AUTH_MODE_API, AUTH_MODE_LOCAL, ClaudeReviewerAdapter  # noqa: E402
from orchestrator.review_dispatcher import process_one_review  # noqa: E402
from orchestrator.supervisor import SupervisorConfig, process_once, run_forever  # noqa: E402

STOP = False


def _stop(signum: int, frame: object) -> None:
    del signum, frame
    global STOP
    STOP = True


def main() -> int:
    parser = argparse.ArgumentParser(description="Physical supervisor (builders + Claude reviewer)")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument(
        "--agents",
        default="composer,claude-reviewer",
        help="Comma-separated: composer,codex,claude-reviewer",
    )
    parser.add_argument("--agent", default=None, help="Legacy single builder agent id")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--max-turns", type=int, default=30)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--review-concurrency", type=int, default=1)
    parser.add_argument("--worktree", default=None)
    parser.add_argument("--grok-executable", default=None)
    parser.add_argument("--codex-executable", default=None)
    parser.add_argument("--claude-executable", default=None)
    parser.add_argument("--auth-mode", choices=[AUTH_MODE_LOCAL, AUTH_MODE_API], default=AUTH_MODE_LOCAL)
    parser.add_argument("--no-codex-fallback", action="store_true")
    parser.add_argument("--no-apply-verdicts", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    agents = {a.strip().lower() for a in (args.agents or "").split(",") if a.strip()}
    if args.agent:
        agents.add(args.agent.strip().lower())
    if not agents:
        agents = {"composer", "claude-reviewer"}

    builder_agents = [a for a in agents if a in {"composer", "codex", "grok"}]
    enable_reviewer = "claude-reviewer" in agents or "claude" in agents

    builder_cfg = SupervisorConfig(
        agent=builder_agents[0] if builder_agents else "composer",
        poll_seconds=max(1, args.poll_seconds),
        max_turns=args.max_turns,
        timeout_seconds=args.timeout_seconds,
        max_concurrency=max(1, args.max_concurrency),
        worktree=args.worktree,
        grok_executable=args.grok_executable,
        codex_executable=args.codex_executable,
        allow_codex_fallback=not args.no_codex_fallback,
    )

    def tick() -> list[dict]:
        reports: list[dict] = []
        for agent in builder_agents or ["composer"]:
            cfg = SupervisorConfig(
                agent=agent if agent != "grok" else "composer",
                poll_seconds=builder_cfg.poll_seconds,
                max_turns=builder_cfg.max_turns,
                timeout_seconds=builder_cfg.timeout_seconds,
                max_concurrency=builder_cfg.max_concurrency,
                worktree=builder_cfg.worktree,
                grok_executable=builder_cfg.grok_executable,
                codex_executable=builder_cfg.codex_executable,
                allow_codex_fallback=builder_cfg.allow_codex_fallback,
            )
            reports.append({"layer": "builder", "agent": agent, **process_once(root, config=cfg)})
        if enable_reviewer:
            adapter = ClaudeReviewerAdapter(
                root,
                claude_executable=args.claude_executable,
                auth_mode=args.auth_mode,
            )
            reports.append(
                {
                    "layer": "reviewer",
                    **process_one_review(
                        root,
                        adapter=adapter,
                        review_concurrency=max(1, args.review_concurrency),
                        timeout_seconds=args.timeout_seconds,
                        apply=not args.no_apply_verdicts,
                    ),
                }
            )
        return reports

    if args.once:
        reports = tick()
        print(json.dumps(reports, indent=2, sort_keys=True, default=str))
        # exit 0 if all idle/completed/skipped/deferred/blocked_auth etc non-crash
        return 0

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    while not STOP:
        reports = tick()
        print(json.dumps(reports, sort_keys=True, default=str), flush=True)
        time.sleep(max(1, args.poll_seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
