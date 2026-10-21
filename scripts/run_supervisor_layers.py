#!/usr/bin/env python3
"""Run independently supervised builder and Claude-reviewer layers."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from orchestrator.layer_supervisor import LayerSupervisor


def main() -> int:
    return LayerSupervisor(REPO_ROOT, {
        "builder": [sys.executable, str(REPO_ROOT / "scripts/run_orchestrator.py"), "--root", str(REPO_ROOT)],
        "claude": [sys.executable, str(REPO_ROOT / "scripts/run_claude_event_consumer.py"), "--root", str(REPO_ROOT)],
    }).run()


if __name__ == "__main__":
    raise SystemExit(main())
