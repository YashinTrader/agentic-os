#!/usr/bin/env python3
"""Create dispatch approval records only — does not execute."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.approval_contract import approval_record_to_dict  # noqa: E402
from dispatch.approval_store import build_approval_record, save_approval_record  # noqa: E402
from dispatch.executor import load_preview  # noqa: E402
from dispatch.executor_contract import resolve_adapter_for_request  # noqa: E402
from dispatch.preview import utc_now  # noqa: E402


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Create dispatch approval record (no execution).")
    p.add_argument("--root", default=str(REPO_ROOT), help="Repository root.")
    p.add_argument("--preview", required=True, help="Path to dispatch preview JSON.")
    p.add_argument("--level", required=True, choices=["none", "reviewer", "human", "blocked"])
    p.add_argument("--approved-by", required=True, help="Approver identity string.")
    p.add_argument(
        "--approver-type",
        default="reviewer",
        choices=["human", "reviewer", "system"],
        help="Approver type (human approvals require --approver-type human).",
    )
    p.add_argument("--ttl-minutes", type=int, help="Override default TTL minutes.")
    p.add_argument("--notes", default="", help="Optional approval notes.")
    p.add_argument("--json", action="store_true", help="Output full approval record JSON.")
    return p


def main() -> int:
    args = parser().parse_args()
    root = Path(args.root).resolve()
    preview_path = Path(args.preview)
    if not preview_path.is_absolute():
        preview_path = (root / preview_path).resolve()

    if args.level == "human" and args.approver_type != "human":
        print(
            "error: human approval requires --approver-type human",
            file=sys.stderr,
        )
        return 2

    try:
        preview = load_preview(preview_path)
        adapter_id = str(preview.get("adapter_id", ""))
        adapter = resolve_adapter_for_request(root, adapter_id)
        record = build_approval_record(
            preview,
            approval_level=args.level,
            approved_by=args.approved_by,
            approver_type=args.approver_type,
            ttl_minutes=args.ttl_minutes,
            notes=args.notes,
            adapter=adapter,
        )
        path = save_approval_record(root, record)
    except Exception as exc:
        print(f"approve failed: {exc}", file=sys.stderr)
        return 1

    try:
        from protocol.emit_event import append_event

        append_event(
            root,
            agent="dispatch-approve",
            event_type="approval_record_created",
            task_id=str(preview.get("task_id", "")),
            detail=f"approval_id={record.approval_id} level={args.level}",
            ref=str(path.relative_to(root)),
        )
    except Exception as exc:
        print(f"warning: could not append event: {exc}", file=sys.stderr)

    if args.json:
        print(json.dumps(approval_record_to_dict(record), indent=2, ensure_ascii=False))
    else:
        print("Approval record created (not executed)")
        print(f"  Approval ID:   {record.approval_id}")
        print(f"  Preview hash:  {record.preview_hash[:16]}...")
        print(f"  Level:         {record.approval_level}")
        print(f"  Approver:      {record.approved_by} ({record.approver_type})")
        print(f"  Expires:       {record.expires_at}")
        print(f"  Path:          {path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())