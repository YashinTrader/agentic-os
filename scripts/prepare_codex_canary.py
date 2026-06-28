#!/usr/bin/env python3
"""Prepare documentation-only Codex canary package — no execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_canary_contract import (  # noqa: E402
    build_canary_contract,
    build_canary_file_content,
    expected_canary_relative_path,
)
from dispatch.codex_activation import build_draft_activation_manifest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare Codex canary documentation package (no execution).")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--reviewed-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--cli-version", default="0.136.0")
    parser.add_argument("--cli-help-hash", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = build_canary_contract()
    rel_path = expected_canary_relative_path(args.run_id)
    preview = {
        "run_id": args.run_id,
        "canary_relative_path": rel_path,
        "canary_contract_hash": contract.contract_hash,
        "documentation_only": True,
        "sample_content": build_canary_file_content(run_id=args.run_id),
        "status": "prepared_not_executed",
    }
    manifest = build_draft_activation_manifest(
        root,
        activation_id=f"activation-{args.run_id}",
        reviewed_commit_sha=args.reviewed_sha,
        base_sha=args.base_sha,
        cli_version=args.cli_version,
        cli_help_hash=args.cli_help_hash or "unreviewed",
        status="awaiting_human_approval",
    )

    out_dir = root / "runtime" / "dispatch" / "runs" / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "canary_preview.json").write_text(json.dumps(preview, indent=2), encoding="utf-8")

    activation_dir = root / "runtime" / "dispatch" / "codex_activation"
    activation_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = activation_dir / f"{manifest['activation_id']}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    if args.json:
        print(json.dumps({"preview": preview, "manifest_path": str(manifest_path)}, indent=2))
    else:
        print(f"Prepared canary preview for {args.run_id} (not executed)")
        print(f"  Expected file: {rel_path}")
        print(f"  Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())