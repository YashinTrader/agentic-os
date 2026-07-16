#!/usr/bin/env python3
"""Prepare Codex canary activation package — no execution, no worktree allocation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_activation import (  # noqa: E402
    activation_bundle_dir,
    build_activation_manifest_v2,
    build_human_approval_request,
)
from dispatch.codex_canary_contract import (  # noqa: E402
    build_canary_contract,
    build_canary_file_content,
    expected_canary_relative_path,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare Codex canary package (no execution).")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--activation", required=True, help="Activation bundle id")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--reviewed-sha", required=True)
    parser.add_argument("--cli-version", default="0.136.0")
    parser.add_argument("--cli-help-hash", default="unreviewed")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    bundle = activation_bundle_dir(root, args.activation)
    bundle.mkdir(parents=True, exist_ok=True)

    contract = build_canary_contract(reviewed_commit_sha=args.reviewed_sha, cli_version=args.cli_version)
    rel_path = expected_canary_relative_path(args.run_id)

    manifest = build_activation_manifest_v2(
        root,
        activation_id=args.activation,
        reviewed_commit_sha=args.reviewed_sha,
        cli_version=args.cli_version,
        cli_help_hash=args.cli_help_hash,
        status="awaiting_claude_review",
    )
    request = build_human_approval_request(
        root,
        activation_id=args.activation,
        reviewed_commit_sha=args.reviewed_sha,
        cli_version=args.cli_version,
    )
    preflight = {
        "activation_id": args.activation,
        "run_id": args.run_id,
        "status": "preflight_complete_no_live_run",
        "worktree_allocated": False,
        "codex_subprocess_invoked": False,
        "phase3_7b_authorization_required": True,
        "live_run_authorized": False,
    }
    preview = {
        "run_id": args.run_id,
        "canary_relative_path": rel_path,
        "canary_contract_hash": contract.contract_hash,
        "sample_content": build_canary_file_content(run_id=args.run_id),
        "status": "prepared_not_executed",
    }

    (bundle / "activation_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    (bundle / "human_approval_request.json").write_text(
        json.dumps(request, indent=2, sort_keys=True), encoding="utf-8"
    )
    (bundle / "preflight.json").write_text(json.dumps(preflight, indent=2, sort_keys=True), encoding="utf-8")
    (bundle / "canary_preview.json").write_text(json.dumps(preview, indent=2, sort_keys=True), encoding="utf-8")

    if args.json:
        print(
            json.dumps(
                {
                    "bundle_dir": str(bundle),
                    "manifest": str(bundle / "activation_manifest.json"),
                    "expected_file": rel_path,
                },
                indent=2,
            )
        )
    else:
        print(f"Prepared activation package {args.activation} (not executed)")
        print(f"  Bundle: {bundle}")
        print(f"  Expected canary file: {rel_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())