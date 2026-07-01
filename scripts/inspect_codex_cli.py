#!/usr/bin/env python3
"""Read-only Codex CLI discovery — fixed argv, shell=False, no prompt execution."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_cli_compatibility import evaluate_cli_compatibility  # noqa: E402

CODEX_EXECUTABLE = "codex"
DISCOVERY_TIMEOUT_SECONDS = 30
FIXED_INVOCATIONS: tuple[tuple[str, ...], ...] = (
    ("--version",),
    ("--help",),
    ("exec", "--help"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _combined_output(stdout: str, stderr: str) -> str:
    parts = [part.strip() for part in (stdout, stderr) if part and part.strip()]
    return "\n".join(parts)


def run_readonly(executable: str, argv: list[str]) -> dict[str, object]:
    full = [executable, *argv]
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
            "stderr": f"executable not found: {executable}",
            "timed_out": False,
        }


def discover() -> dict[str, object]:
    import shutil

    executable_path = shutil.which(CODEX_EXECUTABLE) or ""
    invocation_executable = executable_path or CODEX_EXECUTABLE
    results = [run_readonly(invocation_executable, list(args)) for args in FIXED_INVOCATIONS]
    version_text = ""
    for item in results:
        if item["argv"][-1] == "--version":
            version_text = _combined_output(
                str(item.get("stdout") or ""),
                str(item.get("stderr") or ""),
            ).splitlines()[0] if _combined_output(
                str(item.get("stdout") or ""),
                str(item.get("stderr") or ""),
            ) else ""
            if version_text:
                break
    discovery = {
        "discovered_at": utc_now(),
        "executable": CODEX_EXECUTABLE,
        "executable_path": executable_path,
        "minimum_supported_version": "0.136.0",
        "non_interactive_subcommand": "exec",
        "invocations": results,
        "version_text": version_text,
        "notes": "Read-only discovery; no prompt execution or agent session started.",
    }
    compat = evaluate_cli_compatibility(discovery, require_installed=bool(executable_path))
    discovery["compatibility"] = compat.record
    return discovery


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect locally installed Codex CLI (read-only).")
    parser.add_argument(
        "--output",
        help="Write JSON discovery report (default: runtime/dispatch/codex_cli_discovery.json).",
    )
    parser.add_argument(
        "--compatibility-output",
        help="Write compatibility record (default: runtime/registry/codex_cli_compatibility.json).",
    )
    parser.add_argument("--root", default=str(REPO_ROOT))
    args = parser.parse_args()

    report = discover()
    root = Path(args.root).resolve()
    out = Path(args.output) if args.output else root / "runtime" / "dispatch" / "codex_cli_discovery.json"
    compat_out = (
        Path(args.compatibility_output)
        if args.compatibility_output
        else root / "runtime" / "registry" / "codex_cli_compatibility.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    compat_out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    compat_record = dict(report.get("compatibility") or {})
    compat_record["invocations"] = report.get("invocations") or []
    compat_out.write_text(json.dumps(compat_record, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("executable_path") else 2


if __name__ == "__main__":
    raise SystemExit(main())