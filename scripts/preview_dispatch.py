#!/usr/bin/env python3
"""Generate dry-run dispatch command preview (Phase 3.0 — no execution)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.preview import (  # noqa: E402
    append_preview_event,
    build_dispatch_preview,
    persist_preview,
)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Build dry-run dispatch preview from orchestration plan (no agent execution)."
    )
    p.add_argument("--root", default=str(REPO_ROOT), help="Repository root.")
    p.add_argument("--adapter", help="Explicit adapter id from agents/adapter_registry.yaml.")
    p.add_argument("--plan", help="Path to plan JSON (default: runtime/orchestrator/latest_plan.json).")
    p.add_argument("--task", help="Optional task YAML path (default: derived from plan task_id).")
    p.add_argument("--json", action="store_true", help="Output full preview JSON.")
    p.add_argument("--no-write", action="store_true", help="Do not write preview artifacts or logs.")
    p.add_argument("--no-log", action="store_true", help="Skip appending agent-events.jsonl event.")
    return p


def main() -> int:
    args = parser().parse_args()
    root = Path(args.root).resolve()

    try:
        preview = build_dispatch_preview(
            root,
            adapter_id=args.adapter,
            plan_path=args.plan,
            task_path=args.task,
        )
    except Exception as exc:
        print(f"preview failed: {exc}", file=sys.stderr)
        return 1

    if not args.no_write:
        paths = persist_preview(root, preview, write_artifacts=True)
        preview["artifact_paths"] = paths
        if not args.no_log:
            try:
                append_preview_event(root, preview)
            except Exception as exc:
                print(f"warning: could not append event: {exc}", file=sys.stderr)

    if args.json:
        print(json.dumps(preview, indent=2, ensure_ascii=False))
        return 0 if preview.get("dispatch_allowed") else 2

    print("Dispatch preview (dry-run — not executed)")
    print(f"  Run ID:           {preview['run_id']}")
    print(f"  Task:             {preview.get('task_id')}")
    print(f"  Adapter:          {preview.get('adapter_id')} ({preview.get('adapter_display_name')})")
    print(f"  Dispatch allowed: {preview.get('dispatch_allowed')}")
    print(f"  Command:          {preview.get('command')}")
    print(f"  Working dir:      {preview.get('working_directory')}")
    print(f"  Timeout (s):      {preview.get('timeout_seconds')}")
    print(f"  Secrets required: {preview.get('secrets_required')}")
    print(f"  Risk gate:        {preview.get('risk_gate', {}).get('approval_level')} — {preview.get('risk_gate', {}).get('approval_reason')}")
    print(f"  Approval gate:    {preview.get('approval_gate', {}).get('approval_status')} ({preview.get('approval_gate', {}).get('approval_level')})")
    print(f"  Logs path:        {preview.get('logs_path')}")
    print(f"  Handoff path:     {preview.get('handoff_path')}")
    print(f"  Rollback:         {preview.get('rollback_strategy')}")
    if preview.get("errors"):
        print("  Errors:")
        for err in preview["errors"]:
            print(f"    - {err}")
    print(f"  {preview.get('statement')}")
    return 0 if preview.get("dispatch_allowed") else 2


if __name__ == "__main__":
    raise SystemExit(main())