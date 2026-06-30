#!/usr/bin/env python3
"""Validate Codex activation readiness only — does not activate or execute."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_activation import (  # noqa: E402
    build_draft_activation_manifest,
    validate_activation_manifest,
)
from dispatch.codex_adapter import (  # noqa: E402
    compute_command_contract_hash,
    load_codex_restricted_adapter,
    validate_codex_argv_contract,
    build_codex_exec_options,
    append_codex_prompt,
    CODEX_EXECUTABLE,
)
from dispatch.codex_canary_contract import compute_canary_contract_hash  # noqa: E402
from dispatch.codex_cli_compatibility import evaluate_cli_compatibility  # noqa: E402
from dispatch.execution_gate import adapter_supports_execution  # noqa: E402
from dispatch.preview import get_adapter_by_id, load_adapter_registry  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Codex activation readiness (no activation).")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--manifest", help="Activation manifest JSON path")
    parser.add_argument("--compatibility", help="CLI compatibility JSON path")
    parser.add_argument("--reviewed-sha", help="Reviewed commit SHA")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    blockers: list[str] = []

    dedicated = load_codex_restricted_adapter(root)
    registry = load_adapter_registry(root)
    registry_adapter = get_adapter_by_id(registry, "codex-restricted") or {}

    if dedicated.get("supports_execution") or adapter_supports_execution(registry_adapter):
        blockers.append("supports_execution must remain false")
    if dedicated.get("promotion_state") != "restricted_candidate":
        blockers.append("promotion_state must be restricted_candidate")

    sample_argv = append_codex_prompt(
        [CODEX_EXECUTABLE, *build_codex_exec_options(dedicated, worktree_path="/wt", agent_output_path="/out/msg.txt")],
        "sample prompt for contract validation",
    )
    blockers.extend(
        validate_codex_argv_contract(
            sample_argv,
            agent_output_path="/out/msg.txt",
            prompt="sample prompt for contract validation",
        )
    )

    for rel in (
        "docs/PHASE_3_6_CODEX_ROLLBACK.md",
        "docs/PHASE_3_6_CODEX_ACTIVATION_READINESS.md",
        "docs/PHASE_3_6_HUMAN_APPROVAL_CHECKLIST.md",
        "docs/PHASE_3_6_CODEX_CANARY_RUNBOOK.md",
        "schemas/codex_activation_manifest.schema.json",
        "schemas/codex_canary_record.schema.json",
    ):
        if not (root / rel).exists():
            blockers.append(f"missing activation package artifact: {rel}")

    compat_path = Path(args.compatibility) if args.compatibility else root / "runtime" / "registry" / "codex_cli_compatibility.json"
    cli_help_hash = None
    compat_data: dict = {}
    if compat_path.exists():
        compat_data = json.loads(compat_path.read_text(encoding="utf-8"))
        compat = evaluate_cli_compatibility(
            {"version_text": compat_data.get("version_raw", ""), "executable_path": compat_data.get("executable_path", ""), "non_interactive_subcommand": "exec", "invocations": []},
            require_installed=False,
        )
        if compat_data.get("help_hash"):
            cli_help_hash = str(compat_data["help_hash"])
        if compat_path.exists() and compat_data.get("compatible") is False and compat_data.get("executable_path"):
            blockers.extend(compat_data.get("incompatibility_reasons") or ["CLI incompatible"])

    manifest_path = Path(args.manifest) if args.manifest else None
    if manifest_path and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        reviewed = args.reviewed_sha or "2af82a9e7e812e05059b69653583d1c78dfa43b1"
        manifest = build_draft_activation_manifest(
            root,
            activation_id="activation-readiness-check",
            reviewed_commit_sha=reviewed,
            base_sha=reviewed,
            cli_version=str(compat_data.get("parsed_version", "0.136.0") if compat_path.exists() else "0.136.0"),
            cli_help_hash=cli_help_hash or "unreviewed",
            status="reviewer_approved",
        )
    result = validate_activation_manifest(
        manifest,
        repo_root=root,
        current_reviewed_sha=args.reviewed_sha,
        cli_help_hash=cli_help_hash,
    )
    blockers.extend(result.blockers)

    if compute_canary_contract_hash() != compute_canary_contract_hash():
        blockers.append("canary contract hash unstable")

    report = {
        "status": "READY_FOR_REVIEW" if not blockers else "BLOCKED",
        "blockers": blockers,
        "command_contract_hash": compute_command_contract_hash(),
        "canary_contract_hash": compute_canary_contract_hash(),
        "supports_execution": False,
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(report["status"])
        for item in blockers:
            print(f"  - {item}")

    if report["status"] == "ACTIVE" or report["status"] == "EXECUTABLE":
        return 2
    return 0 if report["status"] == "READY_FOR_REVIEW" else 1


if __name__ == "__main__":
    raise SystemExit(main())