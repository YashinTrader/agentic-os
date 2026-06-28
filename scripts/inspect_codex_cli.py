#!/usr/bin/env python3
"""Read-only Codex CLI discovery — fixed argv, shell=False, no prompt execution."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CODEX_EXECUTABLE = "codex"
DISCOVERY_TIMEOUT_SECONDS = 30
FIXED_INVOCATIONS: tuple[tuple[str, ...], ...] = (
    ("--version",),
    ("--help",),
    ("exec", "--help"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_readonly(argv: list[str]) -> dict[str, object]:
    full = [CODEX_EXECUTABLE, *argv]
    try:
        completed = subprocess.run(
            full,
            capture_output=True,
            text=True,
            timeout=DISCOVERY_TIMEOUT_SECONDS,
            shell=False,
        )
        return {
            "argv": full,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired:
        return {"argv": full, "exit_code": None, "stdout": "", "stderr": "", "timed_out": True}
    except FileNotFoundError:
        return {
            "argv": full,
            "exit_code": None,
            "stdout": "",
            "stderr": f"executable not found: {CODEX_EXECUTABLE}",
            "timed_out": False,
        }


def discover() -> dict[str, object]:
    import shutil

    executable_path = shutil.which(CODEX_EXECUTABLE) or ""
    results = [run_readonly(list(args)) for args in FIXED_INVOCATIONS]
    version_text = ""
    for item in results:
        if item["argv"][-1] == "--version" and isinstance(item.get("stdout"), str):
            version_text = item["stdout"].strip()
            break
    return {
        "discovered_at": utc_now(),
        "executable": CODEX_EXECUTABLE,
        "executable_path": executable_path,
        "minimum_supported_version": "0.136.0",
        "non_interactive_subcommand": "exec",
        "invocations": results,
        "version_text": version_text,
        "notes": "Read-only discovery; no prompt execution or agent session started.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect locally installed Codex CLI (read-only).")
    parser.add_argument(
        "--output",
        help="Write JSON discovery report (default: runtime/dispatch/codex_cli_discovery.json).",
    )
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()

    report = discover()
    root = Path(args.root).resolve()
    out = Path(args.output) if args.output else root / "runtime" / "dispatch" / "codex_cli_discovery.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("executable_path") else 2


if __name__ == "__main__":
    raise SystemExit(main())