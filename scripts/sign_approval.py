#!/usr/bin/env python3
"""Sign an approval record with HMAC-SHA256 (Phase 3.4)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.approval_signing import (  # noqa: E402
    SIGNING_VERSION,
    sign_approval_record,
    upgrade_legacy_to_signable,
    validate_ttl_minutes,
)
from dispatch.atomic_io import atomic_write_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Sign approval record")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--approval", required=True, help="Path to approval JSON")
    parser.add_argument("--approver-type", required=True, choices=["reviewer", "human"])
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--ttl-minutes", type=int, default=None)
    parser.add_argument("--output", help="Output path (default: overwrite with .signed suffix)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    approval_path = Path(args.approval)
    if not approval_path.is_absolute():
        approval_path = (root / approval_path).resolve()

    data = json.loads(approval_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        print("approval must be a JSON object", file=sys.stderr)
        return 2

    ttl_errors = validate_ttl_minutes(args.approver_type, args.ttl_minutes)
    if ttl_errors:
        for err in ttl_errors:
            print(err, file=sys.stderr)
        return 2

    if int(data.get("version", 1)) < SIGNING_VERSION:
        data = upgrade_legacy_to_signable(data)
    data["approver_type"] = args.approver_type
    data["approved_by"] = args.approved_by

    result = sign_approval_record(data, approver_type=args.approver_type)
    if not result.success or result.record is None:
        for err in result.errors:
            print(err, file=sys.stderr)
        return 1

    out = Path(args.output) if args.output else approval_path.with_suffix(".signed.json")
    if not out.is_absolute():
        out = (root / out).resolve()
    atomic_write_json(out, result.record)
    print(json.dumps({"signed_path": str(out), "approval_id": result.record["approval_id"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())