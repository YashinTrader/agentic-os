#!/usr/bin/env python3
"""Verify Codex canary activation package structure — no execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_activation import (  # noqa: E402
    build_human_approval_request,
    validate_activation_manifest_v2,
    validate_human_approval_request,
)
from dispatch.codex_activation_gate import phase3_7b_authorization_path  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Codex canary package (no execution).")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--activation", required=True)
    parser.add_argument("--reviewed-sha", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    blockers: list[str] = []
    bundle = root / "runtime" / "dispatch" / "codex_activation" / args.activation

    manifest_path = bundle / "activation_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        blockers.extend(
            validate_activation_manifest_v2(manifest, repo_root=root, current_reviewed_sha=args.reviewed_sha).blockers
        )
    else:
        blockers.append("activation_manifest.json missing")

    request_path = bundle / "human_approval_request.json"
    if request_path.exists():
        blockers.extend(validate_human_approval_request(json.loads(request_path.read_text(encoding="utf-8"))))
    else:
        blockers.append("human_approval_request.json missing")

    if not phase3_7b_authorization_path(root, args.activation).exists():
        pass  # expected in Phase 3.7A
    else:
        blockers.append("phase3_7b_authorization must be absent in Phase 3.7A")

    report = {"status": "VERIFIED" if not blockers else "BLOCKED", "blockers": blockers}
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(report["status"])
        for item in blockers:
            print(f"  - {item}")
    return 0 if report["status"] == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())