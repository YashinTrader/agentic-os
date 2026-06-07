#!/usr/bin/env python3
"""List roles from roles/registry.yaml with optional filters."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ALLOWED_ROLE_RISK_LEVELS = {"low", "medium", "high"}
ALLOWED_ROLE_APPROVAL_LEVELS = {"none", "reviewer", "human", "blocked"}


def load_roles_registry(root: Path) -> dict[str, Any]:
    path = root / "roles" / "registry.yaml"
    if not path.exists():
        raise FileNotFoundError(f"{path.relative_to(root)} does not exist")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("roles/registry.yaml root must be a YAML mapping")
    roles = data.get("roles", [])
    if not isinstance(roles, list):
        raise ValueError("roles/registry.yaml: roles must be a list")
    return data


def filter_roles(
    roles: list[dict[str, Any]],
    *,
    agent: str | None = None,
    risk: str | None = None,
    approval: str | None = None,
    can_execute: bool | None = None,
    can_review: bool | None = None,
) -> list[dict[str, Any]]:
    filtered = [r for r in roles if isinstance(r, dict)]
    if agent:
        agent_lower = agent.lower()
        filtered = [
            r for r in filtered
            if any(agent_lower == str(a).lower() for a in r.get("allowed_agents", []))
        ]
    if risk:
        filtered = [r for r in filtered if str(r.get("risk_level", "")).lower() == risk.lower()]
    if approval:
        filtered = [r for r in filtered if str(r.get("approval_level", "")).lower() == approval.lower()]
    if can_execute is not None:
        filtered = [r for r in filtered if bool(r.get("can_execute")) == can_execute]
    if can_review is not None:
        filtered = [r for r in filtered if bool(r.get("can_review")) == can_review]
    return filtered


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="List roles from roles/registry.yaml.")
    p.add_argument("--root", default=".", help="Repository root.")
    p.add_argument("--agent", help="Filter by allowed agent id.")
    p.add_argument("--risk", choices=sorted(ALLOWED_ROLE_RISK_LEVELS), help="Filter by risk level.")
    p.add_argument("--approval", choices=sorted(ALLOWED_ROLE_APPROVAL_LEVELS), help="Filter by approval level.")
    p.add_argument("--can-execute", choices=["true", "false"], help="Filter by can_execute flag.")
    p.add_argument("--can-review", choices=["true", "false"], help="Filter by can_review flag.")
    p.add_argument("--json", action="store_true", help="Output JSON.")
    return p


def main() -> int:
    args = parser().parse_args()
    root = Path(args.root).resolve()
    try:
        registry = load_roles_registry(root)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    can_execute = None if args.can_execute is None else args.can_execute == "true"
    can_review = None if args.can_review is None else args.can_review == "true"

    roles = filter_roles(
        registry.get("roles", []),
        agent=args.agent,
        risk=args.risk,
        approval=args.approval,
        can_execute=can_execute,
        can_review=can_review,
    )

    if args.json:
        print(json.dumps({"roles": roles}, indent=2, ensure_ascii=False))
        return 0

    if not roles:
        print("No roles matched the filters.")
        return 0

    print("id                  name                risk     approval   exec  review")
    print("------------------  ------------------  -------  ---------  ----  ------")
    for role in roles:
        print(
            f"{str(role.get('id', '')):<18}  "
            f"{str(role.get('name', '')):<18}  "
            f"{str(role.get('risk_level', '')):<7}  "
            f"{str(role.get('approval_level', '')):<9}  "
            f"{str(role.get('can_execute', '')):<4}  "
            f"{str(role.get('can_review', ''))}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())