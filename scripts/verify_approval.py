#!/usr/bin/env python3
"""Verify signed approval record (Phase 3.4)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.approval_replay import is_approval_consumed  # noqa: E402
from dispatch.approval_signing import verify_signed_approval  # noqa: E402

EXIT_CODES = {
    "valid": 0,
    "invalid": 10,
    "expired": 11,
    "revoked": 12,
    "stale": 13,
    "wrong_key": 14,
    "wrong_scope": 15,
    "replayed": 16,
    "malformed": 17,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify signed approval")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--approval", required=True)
    parser.add_argument("--preview", default=None)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    approval_path = Path(args.approval)
    if not approval_path.is_absolute():
        approval_path = (root / approval_path).resolve()

    record = json.loads(approval_path.read_text(encoding="utf-8"))
    preview = None
    if args.preview:
        preview_path = Path(args.preview)
        if not preview_path.is_absolute():
            preview_path = (root / preview_path).resolve()
        preview = json.loads(preview_path.read_text(encoding="utf-8"))

    result = verify_signed_approval(record, preview=preview)
    status = result.status
    if status == "valid" and is_approval_consumed(root, str(record.get("approval_id", ""))):
        status = "replayed"

    print(status)
    for err in result.errors:
        print(err, file=sys.stderr)
    return EXIT_CODES.get(status, 10)


if __name__ == "__main__":
    raise SystemExit(main())