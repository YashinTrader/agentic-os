#!/usr/bin/env python3
"""Phase 3.7B Codex canary preflight — prepares package; does NOT run Codex."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_preflight_37b import (  # noqa: E402
    AUTHORIZATION_TEMPLATE_FILENAME,
    PHASE37B_DEFAULT_ACTIVATION_ID,
    PHASE37B_TASK_ID,
    allocation_record_to_gate_dict,
    build_authorization_template,
    build_canary_contract_record,
    build_canary_markdown_content,
    build_context_bundle_for_preflight,
    build_live_command_preview,
    build_phase37b_human_request,
    build_phase37b_manifest,
    build_phase37b_preview,
    evaluate_preflight_gates,
    new_immutable_run_id,
    validate_preflight_package,
)
from dispatch.codex_activation import activation_bundle_dir  # noqa: E402
from dispatch.codex_adapter import load_codex_restricted_adapter  # noqa: E402
from dispatch.preview import get_adapter_by_id, load_adapter_registry  # noqa: E402
from dispatch.worktree_allocator import allocate_worktree  # noqa: E402


def _run_cli_inspect(root: Path) -> int:
    script = root / "scripts" / "inspect_codex_cli.py"
    return subprocess.run(
        [sys.executable, str(script), "--root", str(root)],
        cwd=str(root),
        check=False,
    ).returncode


def _is_worktree_clean(worktree_path: Path) -> bool:
    code = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(worktree_path),
        capture_output=True,
        text=True,
        check=False,
    )
    return code.returncode == 0 and not (code.stdout or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare Phase 3.7B Codex canary preflight package.")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--activation", default=PHASE37B_DEFAULT_ACTIVATION_ID)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--reviewed-sha", required=True)
    parser.add_argument("--allocate-worktree", action="store_true", help="Operator-commanded worktree allocation")
    parser.add_argument("--skip-cli-inspect", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    run_id = args.run_id.strip() or new_immutable_run_id()
    activation_id = args.activation

    if not args.skip_cli_inspect:
        inspect_code = _run_cli_inspect(root)
        if inspect_code != 0:
            report = {
                "status": "blocked",
                "reason": "Codex CLI incompatible or not installed",
                "inspect_exit_code": inspect_code,
            }
            print(json.dumps(report, indent=2))
            return 3

    compat_path = root / "runtime" / "registry" / "codex_cli_compatibility.json"
    if not compat_path.is_file():
        print("error: missing codex_cli_compatibility.json — run inspect_codex_cli.py", file=sys.stderr)
        return 3
    cli_compat = json.loads(compat_path.read_text(encoding="utf-8"))
    if not cli_compat.get("compatible"):
        report = {
            "status": "blocked",
            "reason": "CLI incompatible with Phase 3.6 command contract",
            "incompatibility_reasons": cli_compat.get("incompatibility_reasons", []),
        }
        print(json.dumps(report, indent=2))
        return 3

    allocation_record: dict | None = None
    allocation_meta: dict[str, object] = {"allocated": False}
    if args.allocate_worktree:
        result = allocate_worktree(
            root,
            task_id=PHASE37B_TASK_ID,
            run_id=run_id,
            base_sha=args.reviewed_sha,
            owner="operator-preflight",
        )
        if not result.success or result.record is None:
            print(json.dumps({"status": "blocked", "allocation_errors": result.errors}, indent=2))
            return 1
        allocation_record = allocation_record_to_gate_dict(result.record)
        wt_path = Path(str(allocation_record.get("worktree_path", "")))
        allocation_meta = {
            "allocated": True,
            "allocation_id": allocation_record.get("allocation_id"),
            "branch": allocation_record.get("branch_name"),
            "worktree_path": allocation_record.get("worktree_path"),
            "base_sha": allocation_record.get("base_sha"),
            "clean": _is_worktree_clean(wt_path) if wt_path.exists() else False,
            "status": allocation_record.get("status"),
        }
    else:
        print("warning: worktree not allocated; use --allocate-worktree for full preflight", file=sys.stderr)

    expected_path = f"docs/codex-canary-{run_id.replace('canary-', '')[:60]}.md"
    if not expected_path.startswith("docs/codex-canary-"):
        expected_path = f"docs/codex-canary-{run_id}.md"[:80]

    from dispatch.codex_canary_contract import expected_canary_relative_path

    expected_path = expected_canary_relative_path(run_id)

    context_bundle_hash = ""
    context_info: dict[str, object] = {}
    preview: dict[str, object] = {"status": "preview_pending_allocation"}
    if allocation_record:
        ctx = build_context_bundle_for_preflight(
            root,
            run_id=run_id,
            worktree_path=str(allocation_record.get("worktree_path", "")),
            base_sha=str(allocation_record.get("base_sha", "")),
            expected_file=expected_path,
            preview=preview,
        )
        context_bundle_hash = str(ctx.get("bundle_hash", ""))
        context_info = ctx
        preview = build_phase37b_preview(
            root,
            run_id=run_id,
            task_id=PHASE37B_TASK_ID,
            allocation_record=allocation_record,
            cli_compatibility=cli_compat,
            canary_contract=build_canary_contract_record(
                run_id=run_id,
                reviewed_commit_sha=args.reviewed_sha,
                cli_version=str(cli_compat.get("parsed_version") or cli_compat.get("version_raw", "")),
                context_bundle_hash=context_bundle_hash,
                expected_relative_path=expected_path,
            ),
            context_bundle_hash=context_bundle_hash,
        )

    canary_contract = build_canary_contract_record(
        run_id=run_id,
        reviewed_commit_sha=args.reviewed_sha,
        cli_version=str(cli_compat.get("parsed_version") or cli_compat.get("version_raw", "")),
        context_bundle_hash=context_bundle_hash,
        expected_relative_path=expected_path,
    )

    manifest = build_phase37b_manifest(
        root,
        activation_id=activation_id,
        reviewed_commit_sha=args.reviewed_sha,
        cli_version=str(cli_compat.get("parsed_version") or cli_compat.get("version_raw", "")),
        cli_help_hash=str(cli_compat.get("help_hash", "")),
        context_bundle_hash=context_bundle_hash,
        worktree_allocation_id=str((allocation_record or {}).get("allocation_id", "")),
    )
    manifest["canary_contract_hash"] = str(canary_contract.get("contract_hash", ""))

    human_request = build_phase37b_human_request(
        root,
        activation_id=activation_id,
        reviewed_commit_sha=args.reviewed_sha,
        cli_version=str(cli_compat.get("parsed_version") or cli_compat.get("version_raw", "")),
        context_bundle_hash=context_bundle_hash,
        worktree_path=str((allocation_record or {}).get("worktree_path", "")),
        expected_file=expected_path,
        run_id=run_id,
    )

    auth_template = build_authorization_template(
        activation_id=activation_id,
        task_id=PHASE37B_TASK_ID,
        run_id=run_id,
        reviewed_commit_sha=args.reviewed_sha,
        canary_contract_hash=str(canary_contract.get("contract_hash", "")),
        context_bundle_hash=context_bundle_hash,
        preview_hash=str(preview.get("preview_hash", "")),
        worktree_allocation_id=str((allocation_record or {}).get("allocation_id", "")),
        expected_file=expected_path,
    )

    registry = load_adapter_registry(root)
    registry_adapter = get_adapter_by_id(registry, "codex-restricted") or {}
    dedicated = load_codex_restricted_adapter(root)
    gate_report = evaluate_preflight_gates(
        root,
        registry_adapter=registry_adapter,
        dedicated_adapter=dedicated,
        activation_manifest=manifest,
        cli_compatibility=cli_compat,
        allocation_record=allocation_record,
        human_request=human_request,
    )

    bundle = activation_bundle_dir(root, activation_id)
    bundle.mkdir(parents=True, exist_ok=True)

    preflight = {
        "activation_id": activation_id,
        "task_id": PHASE37B_TASK_ID,
        "run_id": run_id,
        "status": "preflight_complete_no_live_run",
        "worktree_allocated": bool(allocation_record),
        "codex_subprocess_invoked": False,
        "approval_consumed": False,
        "phase3_7b_authorization_required": True,
        "live_run_authorized": False,
        "dry_run_blocked": gate_report.blocked,
        "dry_run_blockers": gate_report.blocked_reasons,
    }

    live_commands = build_live_command_preview(
        activation_id=activation_id,
        run_id=run_id,
        allocation_id=str((allocation_record or {}).get("allocation_id", "ALLOCATION_ID")),
        approval_placeholder="runtime/approvals/<signed-human-approval>.json",
        authorization_placeholder=f"runtime/dispatch/codex_activation/{activation_id}/phase3_7b_authorization.json",
    )

    (bundle / "activation_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (bundle / "human_approval_request.json").write_text(
        json.dumps(human_request, indent=2, sort_keys=True), encoding="utf-8"
    )
    (bundle / AUTHORIZATION_TEMPLATE_FILENAME).write_text(
        json.dumps(auth_template, indent=2, sort_keys=True), encoding="utf-8"
    )
    (bundle / "canary_contract.json").write_text(json.dumps(canary_contract, indent=2, sort_keys=True), encoding="utf-8")
    (bundle / "execution_preview.json").write_text(json.dumps(preview, indent=2, sort_keys=True), encoding="utf-8")
    (bundle / "preflight.json").write_text(json.dumps(preflight, indent=2, sort_keys=True), encoding="utf-8")
    (bundle / "live_command_preview.json").write_text(
        json.dumps(live_commands, indent=2, sort_keys=True), encoding="utf-8"
    )
    if allocation_record:
        (bundle / "worktree_allocation.json").write_text(
            json.dumps(allocation_record, indent=2, sort_keys=True), encoding="utf-8"
        )
    if context_info:
        (bundle / "context_bundle_report.json").write_text(
            json.dumps(context_info, indent=2, sort_keys=True), encoding="utf-8"
        )

    (root / "docs" / "PHASE_3_7B_HUMAN_APPROVAL_REQUEST.md").write_text(
        _human_approval_markdown(human_request, manifest, live_commands),
        encoding="utf-8",
    )

    package_blockers = validate_preflight_package(root, activation_id, reviewed_sha=args.reviewed_sha)

    report = {
        "status": "prepared" if not package_blockers else "package_invalid",
        "activation_id": activation_id,
        "task_id": PHASE37B_TASK_ID,
        "run_id": run_id,
        "expected_file": expected_path,
        "canary_contract_hash": canary_contract.get("contract_hash"),
        "context_bundle_hash": context_bundle_hash,
        "preview_hash": preview.get("preview_hash"),
        "manifest_status": manifest.get("status"),
        "human_request_status": human_request.get("status"),
        "authorization_template_status": auth_template.get("status"),
        "allocation": allocation_meta,
        "gate_report": {
            "blocked": gate_report.blocked,
            "blocked_reasons": gate_report.blocked_reasons,
            "codex_subprocess_invoked": gate_report.codex_subprocess_invoked,
            "approval_consumed": gate_report.approval_consumed,
        },
        "package_blockers": package_blockers,
        "codex_subprocess_invoked": False,
        "approval_consumed": False,
        "expected_canary_content_hash": canary_contract.get("expected_content_hash"),
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Phase 3.7B preflight prepared: {activation_id}")
        print(f"  Run ID: {run_id}")
        print(f"  Expected file: {expected_path}")
        print(f"  Status: {report['status']}")
        if package_blockers:
            for item in package_blockers:
                print(f"  blocker: {item}")

    if package_blockers:
        return 1
    if not gate_report.blocked:
        return 2
    return 0


def _human_approval_markdown(request: dict, manifest: dict, commands: dict) -> str:
    return "\n".join(
        [
            "# Phase 3.7B Human Approval Request",
            "",
            "## For Gabriel",
            "",
            "**This request does not authorize execution.**",
            "",
            f"- Activation: `{request.get('activation_id')}`",
            f"- Task: `{request.get('task_id')}`",
            f"- Run ID: `{request.get('run_id')}`",
            f"- Reviewed commit: `{request.get('reviewed_commit_sha')}`",
            f"- Codex version: `{manifest.get('cli_version')}`",
            f"- Worktree: `{request.get('worktree_path') or '(allocate before live run)'}`",
            f"- Expected file: `{request.get('expected_file')}`",
            f"- Maximum runs: **1**",
            f"- Timeout: **10 minutes**",
            f"- Approval expiry once signed: **{request.get('approval_expiry_minutes')} minutes**",
            "",
            "## Exposure",
            "",
            "- Possible Codex/OpenAI API token usage for one bounded prompt",
            "- No MCP, merge, push, or deployment",
            "- Failed or timed-out run still consumes the one-shot approval",
            "- Activation suspended after attempt; Claude post-run review required",
            "",
            "## Future live command (do not run until authorized)",
            "",
            "```text",
            str(commands.get("canary_runner", "")),
            "```",
            "",
            "## Emergency disable",
            "",
            "```text",
            str(commands.get("emergency_disable", "")),
            "```",
            "",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())