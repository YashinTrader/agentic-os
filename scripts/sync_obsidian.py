#!/usr/bin/env python3
"""Sync Agentic OS repo state into a local Obsidian vault (one-way)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from integrations.obsidian.mapping import (  # noqa: E402
    load_mapping,
    require_explicit_vault_when_disabled,
    resolve_vault_path,
)
from integrations.obsidian.sync_to_vault import run_sync  # noqa: E402


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="One-way sync from Agentic OS repo to Obsidian vault.")
    p.add_argument("--root", default=str(REPO_ROOT), help="Repository root.")
    p.add_argument("--vault", help="Obsidian vault path (required when sync_enabled is false).")
    p.add_argument("--dry-run", action="store_true", help="Plan notes without writing files.")
    p.add_argument("--force", action="store_true", help="Reserved for future overwrite controls.")
    p.add_argument("--json", action="store_true", help="Output JSON report.")
    return p


def main() -> int:
    args = parser().parse_args()
    root = Path(args.root).resolve()

    try:
        mapping = load_mapping(root)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    dry_run = bool(args.dry_run)
    vault_path = None

    try:
        if args.dry_run:
            dry_run = True
            if args.vault:
                vault_path = resolve_vault_path(args.vault, mapping)
        elif args.vault:
            dry_run = False
            require_explicit_vault_when_disabled(args.vault, mapping)
            vault_path = resolve_vault_path(args.vault, mapping)
        elif mapping.get("vault_path") and mapping.get("sync_enabled") is True:
            dry_run = False
            vault_path = resolve_vault_path(None, mapping)
        else:
            dry_run = bool(mapping.get("dry_run_default", True))
            if not dry_run:
                require_explicit_vault_when_disabled(None, mapping)
                vault_path = resolve_vault_path(None, mapping)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        report = run_sync(root, vault_path, dry_run=dry_run, mapping=mapping)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        mode = "DRY-RUN" if report.dry_run else "SYNC"
        print(f"Obsidian sync ({mode})")
        print(f"  Notes planned: {report.notes_planned}")
        print(f"  Notes written: {report.notes_written}")
        print(f"  Folders created: {len(report.folders_created)}")
        if report.warnings:
            print("  Warnings:")
            for w in report.warnings:
                print(f"    - {w}")
        if report.errors:
            print("  Errors:")
            for e in report.errors:
                print(f"    - {e}")
        if report.report_path:
            print(f"  Report: {report.report_path}")

    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())