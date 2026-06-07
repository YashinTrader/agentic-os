#!/usr/bin/env python3
"""Agentic OS runtime daemon — local CLI discovery and inventory refresh."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from daemon.cli_discovery import run_discovery, utc_now
from daemon.registry_writer import append_discovery_event, write_daemon_status, write_inventory


def repo_root_from_arg(value: str | None) -> Path:
    if value:
        return Path(value).resolve()
    return Path(__file__).resolve().parents[1]


def run_once(root: Path) -> int:
    started_at = utc_now()
    errors: list[str] = []

    try:
        inventory = run_discovery()
    except Exception as exc:  # pragma: no cover - defensive guard for watch mode
        errors.append(f"discovery failed: {exc}")
        inventory = {
            "schema_version": "1.0",
            "generated_at": utc_now(),
            "discovery_method": "local_path_and_read_only_version_probe",
            "summary": {"total": 0, "available": 0, "missing": 0},
            "tools": [],
        }

    try:
        inventory_path = write_inventory(root, inventory)
        status_path = write_daemon_status(
            root,
            mode="once",
            inventory=inventory,
            errors=errors,
            started_at=started_at,
            finished_at=inventory.get("generated_at"),
        )
        append_discovery_event(root, inventory, mode="once")
    except Exception as exc:
        print(f"failed to write daemon artifacts: {exc}", file=sys.stderr)
        return 1

    summary = inventory.get("summary", {})
    print(f"Wrote {inventory_path.relative_to(root).as_posix()}")
    print(f"Wrote {status_path.relative_to(root).as_posix()}")
    print(
        "Discovery complete: "
        f"{summary.get('available', 0)}/{summary.get('total', 0)} tools available"
    )
    return 1 if errors else 0


def run_watch(root: Path, interval: int) -> int:
    print(f"Starting CLI discovery watch mode (interval={interval}s). Press Ctrl+C to stop.")
    try:
        while True:
            code = run_once(root)
            if code != 0:
                print("Watch cycle completed with errors; continuing.", file=sys.stderr)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nWatch mode stopped.")
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agentic OS runtime CLI discovery daemon.")
    parser.add_argument("--root", default=None, help="Repository root. Defaults to repo parent.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Run discovery once and exit.")
    mode.add_argument("--watch", action="store_true", help="Repeat discovery on an interval.")
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Seconds between watch-mode discovery runs. Default: 60.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = repo_root_from_arg(args.root)

    if args.watch:
        if args.interval < 1:
            print("--interval must be >= 1", file=sys.stderr)
            return 2
        return run_watch(root, args.interval)

    # Default and explicit --once behave the same.
    return run_once(root)


if __name__ == "__main__":
    raise SystemExit(main())