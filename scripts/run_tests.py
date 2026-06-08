#!/usr/bin/env python3
"""Install test dependencies and run the full unittest suite."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = REPO_ROOT / "requirements.txt"


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def main() -> int:
    print(f"run_tests: repo={REPO_ROOT} commit={_git_head()}")
    if REQUIREMENTS.exists():
        install = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS), "-q"],
            cwd=REPO_ROOT,
            check=False,
        )
        if install.returncode != 0:
            print("pip install -r requirements.txt failed", file=sys.stderr)
            return install.returncode

    tests = subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-p",
            "test_*.py",
            "-v",
        ],
        cwd=REPO_ROOT,
        check=False,
    )
    return tests.returncode


if __name__ == "__main__":
    raise SystemExit(main())