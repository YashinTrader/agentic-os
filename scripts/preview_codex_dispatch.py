#!/usr/bin/env python3
"""Build Codex restricted adapter preview — no subprocess execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_adapter import (  # noqa: E402
    build_codex_command,
    evaluate_codex_preview_gate,
    load_codex_restricted_adapter,
)
from dispatch.preview import build_dispatch_preview, persist_preview  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview Codex restricted dispatch (no execution).")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--adapter", default="codex-restricted")
    parser.add_argument("--plan", help="Plan JSON path")
    parser.add_argument("--worktree", required=True, help="Allocated worktree path")
    parser.add_argument("--run-id", help="Dispatch run id")
    parser.add_argument("--allocation", help="Allocation record JSON path")
    parser.add_argument("--cli-version", default="0.136.0")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    adapter = load_codex_restricted_adapter(root)

    preview = build_dispatch_preview(root, adapter_id=args.adapter, plan_path=args.plan)
    if args.run_id:
        preview["run_id"] = args.run_id

    allocation = None
    if args.allocation:
        allocation = json.loads(Path(args.allocation).read_text(encoding="utf-8"))

    run_id = str(preview.get("run_id", ""))
    run_dir = root / "runtime" / "dispatch" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    plan = build_codex_command(
        adapter,
        repo_root=root,
        worktree_path=args.worktree,
        run_id=run_id,
        stdout_path=str(run_dir / "codex.stdout.txt"),
        stderr_path=str(run_dir / "codex.stderr.txt"),
        agent_output_path=str(run_dir / "codex_last_message.txt"),
        timeout_seconds=int(preview.get("timeout_seconds") or adapter.get("timeout_seconds") or 600),
        cli_version=args.cli_version,
        allocation_record=allocation,
        task_id=str(preview.get("task_id", "")),
        base_sha=str(preview.get("base_sha") or preview.get("plan_base_sha") or ""),
        scope_paths=preview.get("scope_paths") or ["."],
    )

    preview["command_argv"] = plan.argv
    preview["command"] = " ".join(plan.argv)
    preview["working_directory"] = plan.cwd
    preview["context_bundle_dir"] = plan.context_bundle_dir
    preview["context_bundle_hash"] = plan.context_bundle_hash
    preview["environment_variable_names"] = plan.environment_variable_names
    preview["errors"] = list(preview.get("errors") or []) + plan.blocked_reasons
    preview["errors"].extend(evaluate_codex_preview_gate(adapter, preview, cli_version=args.cli_version))
    preview["dispatch_allowed"] = len(preview["errors"]) == 0

    paths = persist_preview(root, preview, write_artifacts=True)
    preview["artifact_paths"] = paths

    if args.json:
        print(json.dumps(preview, indent=2, ensure_ascii=False))
    else:
        print("Codex restricted preview (not executed)")
        print(f"  Allowed: {preview.get('dispatch_allowed')}")
        print(f"  Command: {preview.get('command')}")
        if preview.get("errors"):
            print("  Errors:")
            for err in preview["errors"]:
                print(f"    - {err}")
    return 0 if preview.get("dispatch_allowed") else 2


if __name__ == "__main__":
    raise SystemExit(main())