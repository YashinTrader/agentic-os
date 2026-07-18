#!/usr/bin/env python3
"""Run composer and Claude-reviewer persistent supervisor layers together."""
from __future__ import annotations
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    commands = [
        [sys.executable, str(REPO_ROOT / "scripts" / "run_orchestrator.py"), "--root", str(REPO_ROOT)],
        [sys.executable, str(REPO_ROOT / "scripts" / "run_claude_event_consumer.py"), "--root", str(REPO_ROOT)],
    ]
    processes = [subprocess.Popen(command, cwd=REPO_ROOT, shell=False) for command in commands]
    try:
        while all(process.poll() is None for process in processes):
            time.sleep(1)
        return next((int(process.returncode) for process in processes if process.returncode), 1)
    except KeyboardInterrupt:
        return 130
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
