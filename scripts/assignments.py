#!/usr/bin/env python3
"""Claude ↔ Grok Build assignment loop CLI (file-based bridge).

Pure file operations: no network, no merge, no push side effects.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.assignment_channel import (  # noqa: E402
    accept_assignment,
    claim_assignment,
    complete_assignment,
    create_assignment_from_task_yaml,
    format_assignment_contract,
    ingest_outbox_results,
    list_assignment_events,
    list_inbox_assignments,
    list_outbox_results,
    list_pending_assignments,
    read_assignment,
    reject_assignment,
    request_changes_assignment,
    resolve_assignment,
    poke_assignment,
    reassign_assignment,
    REASSIGNMENT_REASONS,
    set_assignment_status,
    write_assignment,
)


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, default=str))


def cmd_list(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if args.pending:
        records, errors = list_pending_assignments(root)
    else:
        records, errors = list_inbox_assignments(root)
        if args.status:
            records = [r for r in records if r.status == args.status]
    if args.json:
        _print_json(
            {
                "count": len(records),
                "assignments": [
                    {
                        "assignment_id": r.assignment_id,
                        "task_id": r.task_id,
                        "title": r.title,
                        "status": r.status,
                        "assigned_by": r.assigned_by,
                        "assigned_to": r.assigned_to,
                        "adapter_id": r.adapter_id,
                        "execution_route": r.execution_route,
                        "base_branch": r.base_branch,
                        "new_branch": r.new_branch,
                        "created_at": r.created_at,
                        "source_path": r.source_path,
                        "parse_errors": r.parse_errors,
                    }
                    for r in records
                ],
                "warnings": errors,
            }
        )
    else:
        if not records:
            print("No assignments found.")
        for r in records:
            warn = f"  WARN={r.parse_errors[0]}" if r.parse_errors else ""
            print(
                f"{r.assignment_id}\t{r.status}\t{r.task_id}\t{r.title}{warn}"
            )
        if errors:
            print("warnings:", file=sys.stderr)
            for e in errors:
                print(f"  {e}", file=sys.stderr)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    record, errors = read_assignment(root, args.assignment_id)
    if record is None:
        print(f"assignment not found: {args.assignment_id}", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    if args.json:
        from dispatch.assignment_channel import assignment_to_payload

        _print_json({"assignment": assignment_to_payload(record), "warnings": errors})
    else:
        print(format_assignment_contract(record), end="")
        if errors:
            print("\n# schema warnings:", file=sys.stderr)
            for e in errors:
                print(f"#  {e}", file=sys.stderr)
    return 0


def cmd_claim(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    assignment_id = args.assignment_id
    if not assignment_id:
        pending, errors = list_pending_assignments(root)
        if errors and args.json:
            pass
        if not pending:
            print("No pending assignments to claim.", file=sys.stderr)
            return 1
        assignment_id = pending[0].assignment_id
        if not args.json:
            print(f"Auto-selected pending assignment: {assignment_id}")

    record, errors = claim_assignment(
        root,
        assignment_id,
        claimed_by=args.claimed_by,
        sync_task_yaml=not args.no_task_sync,
    )
    if record is None:
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    if args.json:
        from dispatch.assignment_channel import assignment_to_payload

        _print_json(
            {
                "status": "claimed",
                "assignment": assignment_to_payload(record),
                "warnings": errors,
            }
        )
    else:
        print(f"CLAIMED {record.assignment_id} ({record.task_id})")
        print()
        print(format_assignment_contract(record), end="")
        if errors:
            print("\nwarnings:", file=sys.stderr)
            for e in errors:
                print(f"  {e}", file=sys.stderr)
    return 0


def cmd_complete(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if args.building:
        set_assignment_status(
            root,
            args.assignment_id,
            "building",
            sync_task_yaml=not args.no_task_sync,
        )
    out, errors = complete_assignment(
        root,
        args.assignment_id,
        handoff_path=args.handoff,
        branch_tip_sha=args.branch_tip_sha,
        branch_name=args.branch,
        result_summary=args.summary,
        blocked_reasons=args.blocked or None,
        outbox_status=args.outbox_status,
        sync_task_yaml=not args.no_task_sync,
    )
    if out is None:
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    if args.json:
        _print_json(
            {
                "status": "awaiting_review",
                "outbox": {
                    "assignment_id": out.assignment_id,
                    "task_id": out.task_id,
                    "status": out.status,
                    "handoff_path": out.handoff_path,
                    "branch_tip_sha": out.branch_tip_sha,
                    "branch_name": out.branch_name,
                    "result_summary": out.result_summary,
                    "source_path": out.source_path,
                },
                "warnings": errors,
            }
        )
    else:
        print(f"COMPLETED {out.assignment_id} -> outbox status={out.status}")
        print(f"  handoff: {out.handoff_path}")
        print(f"  branch:  {out.branch_name} @ {out.branch_tip_sha or '(no sha)'}")
        if errors:
            print("warnings:", file=sys.stderr)
            for e in errors:
                print(f"  {e}", file=sys.stderr)
    return 0


def cmd_reassign(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    replacement, errors = reassign_assignment(
        root,
        args.assignment_id,
        reassigned_by=args.actor,
        assigned_to=args.assign_to,
        reason=args.reason,
        poke=args.poke,
        sync_task_yaml=not args.no_task_sync,
    )
    if replacement is None:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    payload = {
        "status": "reassigned",
        "superseded_assignment_id": args.assignment_id,
        "assignment_id": replacement.assignment_id,
        "assigned_to": replacement.assigned_to,
        "adapter_id": replacement.adapter_id,
        "execution_route": replacement.execution_route,
        "wake_state": "notification_queued" if args.poke else "not_requested",
        "warnings": errors,
    }
    if args.json:
        _print_json(payload)
    else:
        print(
            f"REASSIGNED {args.assignment_id} -> {replacement.assignment_id} "
            f"({replacement.assigned_to})"
        )
        print(f"  adapter: {replacement.adapter_id}")
        print(f"  route: {replacement.execution_route}")
        print(f"  poke: {payload['wake_state']}")
        for error in errors:
            print(f"  warning: {error}", file=sys.stderr)
    return 0


def cmd_poke(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    event, errors = poke_assignment(
        root,
        args.assignment_id,
        actor=args.actor,
        message=args.message,
    )
    if event is None:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    if args.json:
        _print_json({"status": "notification_queued", "event": event})
    else:
        print(
            f"POKED {event['target']} for {event['assignment_id']} "
            f"({event['wake_state']})"
        )
    return 0


def cmd_events(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    events, errors = list_assignment_events(root)
    if args.target:
        events = [event for event in events if event.get("target") == args.target]
    if args.unconsumed:
        events = [event for event in events if not event.get("consumed_at")]
    if args.json:
        _print_json({"count": len(events), "events": events, "warnings": errors})
    else:
        for event in events:
            print(
                f"{event.get('event_id')}\t{event.get('event_type')}\t"
                f"{event.get('source')}->{event.get('target')}\t"
                f"{event.get('assignment_id')}"
            )
        for error in errors:
            print(f"warning: {error}", file=sys.stderr)
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    results, errors = ingest_outbox_results(root)
    if args.json:
        _print_json({"count": len(results), "results": results, "warnings": errors})
    else:
        print(f"Ingested {len(results)} outbox result(s).")
        for r in results:
            handoff_ok = "ok" if r.get("handoff_exists") else "MISSING"
            print(
                f"  {r['assignment_id']}\t{r['task_id']}\t"
                f"outbox={r['outbox_status']}\tassignment={r['assignment_status']}\t"
                f"handoff={handoff_ok}\tbranch={r.get('branch_name') or '-'}"
            )
        print("Index: runtime/dispatch/assignments/ingest/latest_ingest.json")
        if errors:
            print("warnings:", file=sys.stderr)
            for e in errors:
                print(f"  {e}", file=sys.stderr)
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    """Claude-side: post a new assignment (from task YAML or explicit fields)."""
    root = Path(args.root).resolve()
    if args.from_task:
        path, errors = create_assignment_from_task_yaml(
            root,
            args.from_task,
            base_branch=args.base_branch,
            base_sha=args.base_sha,
            new_branch=args.new_branch,
            assigned_by=args.assigned_by,
            assigned_to=args.assigned_to,
        )
    else:
        if not args.task_id:
            print("--task-id is required without --from-task", file=sys.stderr)
            return 2
        path, errors = write_assignment(
            root,
            task_id=args.task_id,
            title=args.title or args.task_id,
            goal=args.goal or args.title or args.task_id,
            base_branch=args.base_branch or "main",
            base_sha=args.base_sha,
            new_branch=args.new_branch or "",
            allowed_paths=args.allowed_path or [],
            acceptance_criteria=args.acceptance or [],
            verification_commands=args.verify or [
                "python scripts/validate.py",
                "python scripts/run_tests.py",
            ],
            timeout=args.timeout,
            handoff_path=args.handoff,
            assigned_by=args.assigned_by,
            assigned_to=args.assigned_to,
            task_path=args.task_path or "",
            instructions=args.instructions,
        )
    if path is None:
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    rel = str(path.relative_to(root)).replace("\\", "/")
    if args.json:
        _print_json({"status": "created", "path": rel, "assignment_id": path.stem, "warnings": errors})
    else:
        print(f"Created assignment {path.stem}")
        print(f"  path: {rel}")
        if errors:
            for e in errors:
                print(f"  warning: {e}", file=sys.stderr)
    return 0


def cmd_outbox(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    records, errors = list_outbox_results(root)
    if args.json:
        _print_json(
            {
                "count": len(records),
                "results": [
                    {
                        "assignment_id": r.assignment_id,
                        "task_id": r.task_id,
                        "status": r.status,
                        "handoff_path": r.handoff_path,
                        "branch_tip_sha": r.branch_tip_sha,
                        "branch_name": r.branch_name,
                        "reviewed_by": r.reviewed_by,
                        "reviewed_at": r.reviewed_at,
                        "resolution_note": r.resolution_note,
                        "source_path": r.source_path,
                    }
                    for r in records
                ],
                "warnings": errors,
            }
        )
    else:
        for r in records:
            res = ""
            if r.reviewed_by or r.resolution_note:
                res = f"\treviewed_by={r.reviewed_by or '-'}"
            print(
                f"{r.assignment_id}\t{r.status}\t{r.task_id}\t"
                f"{r.handoff_path or '-'}{res}"
            )
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    """Shared handler for accept / request-changes / reject."""
    root = Path(args.root).resolve()
    resolution = args.resolution
    note = getattr(args, "note", None)
    reviewed_by = getattr(args, "reviewed_by", "claude")

    if resolution == "accepted":
        record, errors = accept_assignment(
            root,
            args.assignment_id,
            note=note,
            reviewed_by=reviewed_by,
            sync_task_yaml=not args.no_task_sync,
        )
    elif resolution == "changes_requested":
        record, errors = request_changes_assignment(
            root,
            args.assignment_id,
            note=note or "",
            reviewed_by=reviewed_by,
            sync_task_yaml=not args.no_task_sync,
        )
    elif resolution == "rejected":
        record, errors = reject_assignment(
            root,
            args.assignment_id,
            note=note or "",
            reviewed_by=reviewed_by,
            sync_task_yaml=not args.no_task_sync,
        )
    else:
        record, errors = resolve_assignment(
            root,
            args.assignment_id,
            resolution=resolution,
            note=note,
            reviewed_by=reviewed_by,
            sync_task_yaml=not args.no_task_sync,
        )

    if record is None:
        for e in errors:
            print(e, file=sys.stderr)
        return 1

    if args.json:
        from dispatch.assignment_channel import assignment_to_payload

        _print_json(
            {
                "status": record.status,
                "assignment": assignment_to_payload(record),
                "warnings": errors,
            }
        )
    else:
        print(
            f"RESOLVED {record.assignment_id} -> {record.status} "
            f"(reviewed_by={record.reviewed_by})"
        )
        if record.resolution_note:
            print(f"  note: {record.resolution_note}")
        if record.status == "changes_requested":
            print("  re-claimable: yes (one correction cycle)")
        if errors:
            print("warnings:", file=sys.stderr)
            for e in errors:
                print(f"  {e}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "File-based Claude↔Grok assignment loop "
            "(list/show/claim/complete/ingest/accept/request-changes/reject)."
        )
    )
    p.add_argument(
        "--root",
        default=str(REPO_ROOT),
        help="Repository root (default: auto-detected).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    list_p = sub.add_parser("list", help="List inbox assignments")
    list_p.add_argument("--pending", action="store_true", help="Only pickable (pending) assignments")
    list_p.add_argument("--status", help="Filter by assignment status")
    list_p.add_argument("--json", action="store_true")
    list_p.set_defaults(func=cmd_list)

    show_p = sub.add_parser("show", help="Show full assignment contract")
    show_p.add_argument("assignment_id")
    show_p.add_argument("--json", action="store_true")
    show_p.set_defaults(func=cmd_show)

    claim_p = sub.add_parser("claim", help="Atomically claim a pending assignment")
    claim_p.add_argument(
        "assignment_id",
        nargs="?",
        default=None,
        help="Assignment id (default: first pending)",
    )
    claim_p.add_argument(
        "--claimed-by",
        default="composer",
        help="Claimant identity (Codex fallback must pass --claimed-by codex)",
    )
    claim_p.add_argument("--no-task-sync", action="store_true")
    claim_p.add_argument("--json", action="store_true")
    claim_p.set_defaults(func=cmd_claim)

    reassign_p = sub.add_parser(
        "reassign",
        help="Supersede an assignment and route its contract to a fallback builder",
    )
    reassign_p.add_argument("assignment_id")
    reassign_p.add_argument("--assign-to", required=True, help="Fallback builder id")
    reassign_p.add_argument("--actor", default="claude", help="Orchestrator identity")
    reassign_p.add_argument("--reason", required=True, choices=sorted(REASSIGNMENT_REASONS))
    reassign_p.add_argument("--poke", action="store_true", help="Queue a builder notification")
    reassign_p.add_argument("--no-task-sync", action="store_true")
    reassign_p.add_argument("--json", action="store_true")
    reassign_p.set_defaults(func=cmd_reassign)

    poke_p = sub.add_parser("poke", help="Queue a notification for the assigned builder")
    poke_p.add_argument("assignment_id")
    poke_p.add_argument("--actor", default="claude", help="Orchestrator identity")
    poke_p.add_argument("--message")
    poke_p.add_argument("--json", action="store_true")
    poke_p.set_defaults(func=cmd_poke)

    events_p = sub.add_parser("events", help="List structured assignment notifications")
    events_p.add_argument("--target")
    events_p.add_argument("--unconsumed", action="store_true")
    events_p.add_argument("--json", action="store_true")
    events_p.set_defaults(func=cmd_events)

    complete_p = sub.add_parser(
        "complete",
        help="Write outbox result and mark assignment awaiting_review",
    )
    complete_p.add_argument("assignment_id")
    complete_p.add_argument("--handoff", help="Handoff path")
    complete_p.add_argument("--branch", help="Branch name")
    complete_p.add_argument("--branch-tip-sha", help="40-char tip SHA")
    complete_p.add_argument("--summary", help="Result summary")
    complete_p.add_argument("--blocked", action="append", default=[], help="Blocked reason")
    complete_p.add_argument(
        "--outbox-status",
        default="awaiting_review",
        choices=["completed", "failed", "blocked", "awaiting_review"],
    )
    complete_p.add_argument(
        "--building",
        action="store_true",
        help="Mark building immediately before complete (optional)",
    )
    complete_p.add_argument("--no-task-sync", action="store_true")
    complete_p.add_argument("--json", action="store_true")
    complete_p.set_defaults(func=cmd_complete)

    ingest_p = sub.add_parser("ingest", help="Reviewer: ingest outbox results")
    ingest_p.add_argument("--json", action="store_true")
    ingest_p.set_defaults(func=cmd_ingest)

    create_p = sub.add_parser("create", help="Reviewer: post a new assignment")
    create_p.add_argument("--from-task", help="Path to tasks/active/*.yaml")
    create_p.add_argument("--task-id")
    create_p.add_argument("--title")
    create_p.add_argument("--goal")
    create_p.add_argument("--base-branch", default="main")
    create_p.add_argument("--base-sha")
    create_p.add_argument("--new-branch")
    create_p.add_argument("--allowed-path", action="append", default=[])
    create_p.add_argument("--acceptance", action="append", default=[])
    create_p.add_argument("--verify", action="append", default=[])
    create_p.add_argument("--timeout", type=int, default=1800)
    create_p.add_argument("--handoff")
    create_p.add_argument("--task-path")
    create_p.add_argument("--instructions")
    create_p.add_argument("--assigned-by", default="claude")
    create_p.add_argument("--assigned-to", default="composer")
    create_p.add_argument("--json", action="store_true")
    create_p.set_defaults(func=cmd_create)

    outbox_p = sub.add_parser("outbox", help="List outbox results")
    outbox_p.add_argument("--json", action="store_true")
    outbox_p.set_defaults(func=cmd_outbox)

    def _add_resolve_args(sp: argparse.ArgumentParser, *, note_required: bool) -> None:
        sp.add_argument("assignment_id")
        sp.add_argument(
            "--note",
            required=note_required,
            help="Reviewer note (required for request-changes/reject)",
        )
        sp.add_argument("--reviewed-by", default="claude")
        sp.add_argument("--no-task-sync", action="store_true")
        sp.add_argument("--json", action="store_true")
        sp.set_defaults(func=cmd_resolve)

    accept_p = sub.add_parser(
        "accept",
        help="Reviewer: accept assignment (awaiting_review -> accepted)",
    )
    accept_p.set_defaults(resolution="accepted")
    _add_resolve_args(accept_p, note_required=False)

    changes_p = sub.add_parser(
        "request-changes",
        help="Reviewer: request changes (awaiting_review -> changes_requested; re-claimable)",
    )
    changes_p.set_defaults(resolution="changes_requested")
    _add_resolve_args(changes_p, note_required=True)

    reject_p = sub.add_parser(
        "reject",
        help="Reviewer: reject assignment (awaiting_review -> rejected)",
    )
    reject_p.set_defaults(resolution="rejected")
    _add_resolve_args(reject_p, note_required=True)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
