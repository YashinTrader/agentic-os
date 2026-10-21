#!/usr/bin/env python3
"""Install test dependencies and run the full unittest suite."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = REPO_ROOT / "requirements.txt"
sys.path.insert(0, str(REPO_ROOT))
from scripts.repository_verification import (
    repository_identity, evidence_block_hash, render_test_evidence,
    test_evidence_from_artifact,
)

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
        if stripped.startswith("Ran ") and " test" in stripped:
            try:
                return int(stripped.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def _write_result(
    exit_code: int,
    output: str | bytes,
    *,
    handoff: Path | None = None,
    command_line: list[str] | None = None,
    skip_install_reason: str | None = None,
    known_exempt_failures: list[str] | None = None,
) -> str:
    # handoff is retained for CLI/API compatibility, never read as evidence input.
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    raw_output = output.encode("utf-8") if isinstance(output, str) else output
    install_metadata = "dependency_install: performed\n" if skip_install_reason is None else (
        f"dependency_install: skipped\ndependency_install_reason: {skip_install_reason}\n"
    )
    raw_output = install_metadata.encode("utf-8") + raw_output
    output_text = raw_output.decode("utf-8", errors="replace")
    test_count = _parse_test_count(output_text)
    origin = _git_toplevel()
    artifact = {
        "timestamp": stamp,
        "dependency_install": "performed" if skip_install_reason is None else "skipped",
        "dependency_install_reason": skip_install_reason or "",
        "known_exempt_failures": json.dumps(known_exempt_failures or []),
        "repo_identity": repository_identity(REPO_ROOT),
        "artifact_origin_path": origin,
        "hostname": platform.node(),
        "python_version": platform.python_version(),
        "command_line": json.dumps(command_line or sys.argv),
        "raw_output_sha256": hashlib.sha256(raw_output).hexdigest(),
        "repo_root": origin,
        "commit": _git_head(short=True),
        "commit_full": _git_head(short=False),
        "python": sys.executable,
        "test_count": str(test_count) if test_count is not None else "",
        "exit_code": str(exit_code),
    }
    evidence = test_evidence_from_artifact(artifact)
    artifact["evidence_block_sha256"] = evidence_block_hash(evidence)
    content = "".join(f"{key}: {value}\n" for key, value in artifact.items()) + "--- raw output ---\n"
    RESULT_PATH.write_bytes(content.encode("utf-8") + raw_output)
    return render_test_evidence(evidence)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path, help="Optional handoff destination label; no existing file required")
    parser.add_argument("--known-exempt-failure", action="append", default=[], help="Explicit exempt test id (repeatable); sealed without changing the true exit code")
    parser.add_argument("--skip-install", action="store_true", help="Use existing dependencies")
    parser.add_argument("--skip-install-reason", help="Required explanation when skipping dependency installation")
    args = parser.parse_args()
    if any(not value.strip() or any(c in value for c in "\r\n") for value in args.known_exempt_failure):
        parser.error("--known-exempt-failure must be a nonempty single-line test id")
    if args.skip_install:
        if not args.skip_install_reason or not args.skip_install_reason.strip():
            parser.error("--skip-install requires a nonempty --skip-install-reason")
        if any(c in args.skip_install_reason for c in "\r\n"):
            parser.error("--skip-install-reason must be a single line")
        args.skip_install_reason = args.skip_install_reason.strip()
    elif args.skip_install_reason is not None:
        parser.error("--skip-install-reason requires --skip-install")
    commit = _git_head()
    print(f"run_tests: repo={REPO_ROOT} commit={commit}")
    if not args.skip_install and REQUIREMENTS.exists():
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
            _write_result(install.returncode, msg, handoff=args.handoff)
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
        check=False,
    )
    combined = tests.stdout + tests.stderr
    if tests.stdout:
        print(tests.stdout.decode("utf-8", errors="replace"), end="")
    if tests.stderr:
        print(tests.stderr.decode("utf-8", errors="replace"), end="", file=sys.stderr)
    evidence_text = _write_result(
        tests.returncode, combined, handoff=args.handoff, command_line=tests.args,
        skip_install_reason=args.skip_install_reason,
        known_exempt_failures=args.known_exempt_failure,
    )
    print(f"run_tests: wrote {RESULT_PATH.relative_to(REPO_ROOT)} exit={tests.returncode}")
    print(evidence_text)
    return tests.returncode


if __name__ == "__main__":
    if __package__:
        from ._console import configure_console
    else:
        from _console import configure_console

    configure_console()
    raise SystemExit(main())
