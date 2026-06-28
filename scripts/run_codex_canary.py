#!/usr/bin/env python3
"""Codex canary runner — refuses until adapter is separately activated."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_adapter import load_codex_restricted_adapter  # noqa: E402
from dispatch.execution_gate import adapter_supports_execution  # noqa: E402
from dispatch.preview import get_adapter_by_id, load_adapter_registry  # noqa: E402


REFUSAL_REASON = (
    "Codex canary refused: adapter supports_execution=false or --execute-canary not authorized. "
    "Complete Claude review and a separate activation task before live canary."
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex canary (blocked until post-activation).")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--execute-canary", action="store_true", help="Explicit operator opt-in")
    parser.add_argument("--allocation", help="Allocation record JSON path")
    parser.add_argument("--approval", help="Signed approval record JSON path")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    registry = load_adapter_registry(root)
    registry_adapter = get_adapter_by_id(registry, "codex-restricted") or {}
    dedicated = load_codex_restricted_adapter(root)

    blocked: list[str] = []
    if not adapter_supports_execution(registry_adapter):
        blocked.append("codex-restricted supports_execution=false")
    if dedicated.get("promotion_state") != "restricted_candidate" and not adapter_supports_execution(dedicated):
        blocked.append("promotion_state does not allow live canary")
    if not args.execute_canary:
        blocked.append("missing --execute-canary operator flag")
    if not args.allocation:
        blocked.append("missing --allocation")
    if not args.approval:
        blocked.append("missing --approval")

    report = {
        "status": "refused",
        "blocked_reasons": blocked if blocked else [REFUSAL_REASON],
        "adapter_supports_execution": adapter_supports_execution(registry_adapter),
        "promotion_state": dedicated.get("promotion_state"),
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(REFUSAL_REASON)
        for reason in report["blocked_reasons"]:
            print(f"  - {reason}")

    return 3


if __name__ == "__main__":
    raise SystemExit(main())