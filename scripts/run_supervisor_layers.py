#!/usr/bin/env python3
"""Run independently supervised builder and Claude-reviewer layers."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from orchestrator.layer_supervisor import LayerSupervisor


from scripts.state_root import resolve_state_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", default=None)
    args = parser.parse_args()
    try:
        root = resolve_state_root(REPO_ROOT, args.state_root)
    except ValueError as exc:
        parser.error(str(exc))
    return LayerSupervisor(root, {
        "builder": [sys.executable, str(REPO_ROOT / "scripts/run_orchestrator.py"), "--state-root", str(root)],
        "claude": [sys.executable, str(REPO_ROOT / "scripts/run_claude_event_consumer.py"), "--state-root", str(root)],
    }).run()


if __name__ == "__main__":
    raise SystemExit(main())
