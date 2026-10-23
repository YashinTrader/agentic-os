#!/usr/bin/env python3
"""Run independently supervised builder and Claude-reviewer layers."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from orchestrator.layer_supervisor import LayerSupervisor
from orchestrator.supervisor_control import control_dir


from root_paths import resolve_state_root, resolve_config_root, export_roots


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", default=None)
    parser.add_argument("--config-root", default=None)
    parser.add_argument('--reset-root-guard', action='store_true')
    parser.add_argument('--actor')
    parser.add_argument('--reason')
    args = parser.parse_args()
    if args.reset_root_guard and (not args.actor or not args.actor.strip() or not args.reason or not args.reason.strip()):
        parser.error('--reset-root-guard requires nonblank --actor and --reason')
    if not args.reset_root_guard and (args.actor or args.reason):
        parser.error('--actor and --reason require --reset-root-guard')
    try:
        root = resolve_state_root(REPO_ROOT, args.state_root)
        if args.reset_root_guard:
            from scripts.stop_supervisor import reset_resilience
            return reset_resilience(root, args.actor, args.reason)
        if (control_dir(root) / "maintenance.json").exists():
            print("maintenance mode: supervisor not started", flush=True)
            return 0
        config_root = resolve_config_root(REPO_ROOT, args.config_root, validate=True)
        export_roots(root, config_root)
    except ValueError as exc:
        parser.error(str(exc))
    return LayerSupervisor(root, {
        "builder": [sys.executable, str(REPO_ROOT / "scripts/run_orchestrator.py"), "--state-root", str(root), "--config-root", str(config_root)],
        "claude": [sys.executable, str(REPO_ROOT / "scripts/run_claude_event_consumer.py"), "--state-root", str(root), "--config-root", str(config_root)],
    }, root_guard=True).run()


if __name__ == "__main__":
    from scripts._console import configure_console
    configure_console()
    raise SystemExit(main())
