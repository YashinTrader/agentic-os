#!/usr/bin/env python3
"""Install test dependencies and run the full unittest suite."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = REPO_ROOT / "requirements.txt"
RESULT_PATH = REPO_ROOT / "runtime" / "unittest_last_run.txt"


def _git_head(short: bool = True) -> str:
    flag = "--short" if short else "HEAD"
    try:
        result = subprocess.run(
            ["git", "rev-parse", flag],
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


def _git_toplevel() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return str(REPO_ROOT)


def _parse_test_count(output: str) -> int | None:
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if stripped.startswith("Ran ") and " tests" in stripped:
            try:
                return int(stripped.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def _write_result(exit_code: int, output: str) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    tail = "\n".join(output.strip().splitlines()[-25:])
    test_count = _parse_test_count(output)
    count_line = f"test_count: {test_count}\n" if test_count is not None else ""
    RESULT_PATH.write_text(
        f"timestamp: {stamp}\n"
        f"repo_root: {_git_toplevel()}\n"
        f"commit: {_git_head(short=True)}\n"
        f"commit_full: {_git_head(short=False)}\n"
        f"python: {sys.executable}\n"
        f"{count_line}"
        f"exit_code: {exit_code}\n"
        f"--- tail ---\n"
        f"{tail}\n",
        encoding="utf-8",
    )


def main() -> int:
    commit = _git_head()
    print(f"run_tests: repo={REPO_ROOT} commit={commit}")
    if REQUIREMENTS.exists():
        install = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS), "-q"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if install.returncode != 0:
            msg = install.stderr or install.stdout or "pip install failed"
            print(msg, file=sys.stderr)
            _write_result(install.returncode, msg)
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
        capture_output=True,
        text=True,
        check=False,
    )
    combined = tests.stdout + tests.stderr
    if tests.stdout:
        print(tests.stdout, end="")
    if tests.stderr:
        print(tests.stderr, end="", file=sys.stderr)
    _write_result(tests.returncode, combined)
    print(f"run_tests: wrote {RESULT_PATH.relative_to(REPO_ROOT)} exit={tests.returncode}")
    return tests.returncode


if __name__ == "__main__":
    raise SystemExit(main())