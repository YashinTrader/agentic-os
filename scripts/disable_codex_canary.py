#!/usr/bin/env python3
"""Write emergency disable record for Codex activation — no source config edits."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_activation_gate import disabled_path  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser(description="Emergency-disable Codex canary activation bundle.")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--activation", required=True, help="Activation id")
    parser.add_argument("--reason", required=True, help="Disable reason")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out = disabled_path(root, args.activation)
    out.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "activation_id": args.activation,
        "disabled": True,
        "reason": args.reason,
        "disabled_at": utc_now(),
        "source_config_modified": False,
    }
    out.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")

    if args.json:
        print(json.dumps({"path": str(out), "record": record}, indent=2))
    else:
        print(f"Disabled activation {args.activation}: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())