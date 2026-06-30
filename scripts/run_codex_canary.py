#!/usr/bin/env python3
"""Codex canary runner — stops before approval claim; Phase 3.7B required for live run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_activation_gate import (  # noqa: E402
    PHASE3_7B_BLOCKED_REASON,
    evaluate_activation_gates,
)
from dispatch.codex_adapter import load_codex_restricted_adapter  # noqa: E402
from dispatch.preview import get_adapter_by_id, load_adapter_registry  # noqa: E402

REFUSAL_REASON = (
    "Codex canary refused: activation package incomplete or Phase 3.7B authorization absent. "
    "No Codex subprocess invoked."
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex canary (blocked until Phase 3.7B).")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--execute-canary", action="store_true", help="Explicit operator opt-in")
    parser.add_argument("--dry-run", action="store_true", help="Validate gates only (still refuses live run)")
    parser.add_argument("--allocation", help="Allocation record JSON path")
    parser.add_argument("--approval", help="Signed approval record JSON path")
    parser.add_argument("--manifest", help="Activation manifest JSON path")
    parser.add_argument("--compatibility", help="CLI compatibility JSON path")
    parser.add_argument("--reviewed-sha", help="Reviewed commit SHA")
    parser.add_argument("--activation-id", help="Activation bundle id")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    registry = load_adapter_registry(root)
    registry_adapter = get_adapter_by_id(registry, "codex-restricted") or {}
    dedicated = load_codex_restricted_adapter(root)

    activation_manifest = None
    if args.manifest:
        activation_manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))

    activation_id = args.activation_id or str((activation_manifest or {}).get("activation_id", ""))

    human_approval = None
    if args.approval:
        human_approval = json.loads(Path(args.approval).read_text(encoding="utf-8"))

    allocation_record = None
    if args.allocation:
        allocation_record = json.loads(Path(args.allocation).read_text(encoding="utf-8"))

    cli_compatibility = None
    compat_path = (
        Path(args.compatibility)
        if args.compatibility
        else root / "runtime" / "registry" / "codex_cli_compatibility.json"
    )
    if compat_path.exists():
        cli_compatibility = json.loads(compat_path.read_text(encoding="utf-8"))

    gate_result = evaluate_activation_gates(
        root,
        registry_adapter=registry_adapter,
        dedicated_adapter=dedicated,
        execute_flag=args.execute_canary,
        activation_manifest=activation_manifest,
        human_approval=human_approval,
        cli_compatibility=cli_compatibility,
        allocation_record=allocation_record,
        reviewed_sha=args.reviewed_sha,
        activation_id=activation_id or None,
        require_phase3_7b=True,
    )

    blocked = list(gate_result.blocked_reasons)
    if args.dry_run:
        blocked.append("dry-run mode refuses live Codex execution")
    if PHASE3_7B_BLOCKED_REASON not in blocked:
        blocked.append(PHASE3_7B_BLOCKED_REASON)

    report = {
        "status": "refused",
        "blocked_reasons": blocked if blocked else [REFUSAL_REASON],
        "gate_results": gate_result.gate_results,
        "adapter_supports_execution": registry_adapter.get("supports_execution", False),
        "promotion_state": dedicated.get("promotion_state"),
        "codex_subprocess_invoked": False,
        "approval_consumed": False,
        "stops_before_step": 16,
        "phase3_7b_authorization_present": gate_result.gate_results.get("phase3_7b_authorization", False),
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(REFUSAL_REASON)
        for reason in report["blocked_reasons"]:
            print(f"  - {reason}")

    return 3


if __name__ == "__main__":
    raise SystemExit(main())