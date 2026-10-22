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
    args = parser.parse_args()
    try:
        root = resolve_state_root(REPO_ROOT, args.state_root)
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
    }).run()


if __name__ == "__main__":
    from scripts._console import configure_console
    configure_console()
    raise SystemExit(main())
