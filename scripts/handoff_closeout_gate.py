#!/usr/bin/env python3
"""Mandatory handoff closeout gate: verify_repository_verification + validate."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> int:
    proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run verify_repository_verification and validate.py (both must pass)"
    )
    parser.add_argument("handoff", type=Path, help="Handoff markdown path (repo-relative or absolute)")
    args = parser.parse_args()

    handoff = args.handoff if args.handoff.is_absolute() else REPO_ROOT / args.handoff
    if not handoff.exists():
        print(f"handoff missing: {handoff}", file=sys.stderr)
        return 2

    verify_cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "verify_repository_verification.py"),
        str(handoff.relative_to(REPO_ROOT)),
    ]
    validate_cmd = [sys.executable, str(REPO_ROOT / "scripts" / "validate.py")]

    verify_code = _run(verify_cmd)
    validate_code = _run(validate_cmd)

    if verify_code != 0:
        print(f"handoff_closeout_gate: verify failed (exit {verify_code})", file=sys.stderr)
        return verify_code
    if validate_code != 0:
        print(f"handoff_closeout_gate: validate failed (exit {validate_code})", file=sys.stderr)
        return validate_code

    print("handoff_closeout_gate: verified and validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())