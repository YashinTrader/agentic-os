#!/usr/bin/env python3
"""List MCP servers from mcps/registry.yaml with optional filters."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

MCP_REQUIRED_FIELDS = {
    "id",
    "name",
    "description",
    "status",
    "transport",
    "command",
    "args",
    "endpoint",
    "env_vars_required",
    "requires_secret",
    "allowed_agents",
    "capabilities",
    "risk_level",
    "approval_level",
    "notes",
}

ALLOWED_MCP_STATUSES = {"planned", "configured", "available", "disabled", "error"}
ALLOWED_MCP_TRANSPORTS = {"stdio", "streamable_http", "sse", "unknown"}
ALLOWED_MCP_RISK_LEVELS = {"low", "medium", "high"}
ALLOWED_MCP_APPROVAL_LEVELS = {"none", "reviewer", "human", "blocked"}


def load_mcps_registry(root: Path) -> dict[str, Any]:
    path = root / "mcps" / "registry.yaml"
    if not path.exists():
        raise FileNotFoundError(f"{path.relative_to(root)} does not exist")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("mcps/registry.yaml root must be a YAML mapping")
    mcps = data.get("mcps", [])
    if not isinstance(mcps, list):
        raise ValueError("mcps/registry.yaml: mcps must be a list")
    return data


def filter_mcps(
    mcps: list[dict[str, Any]],
    *,
    agent: str | None = None,
    status: str | None = None,
    transport: str | None = None,
) -> list[dict[str, Any]]:
    filtered = [m for m in mcps if isinstance(m, dict)]
    if agent:
        agent_lower = agent.lower()
        filtered = [
            m for m in filtered
            if any(agent_lower == str(a).lower() for a in m.get("allowed_agents", []))
        ]
    if status:
        filtered = [m for m in filtered if str(m.get("status", "")).lower() == status.lower()]
    if transport:
        filtered = [m for m in filtered if str(m.get("transport", "")).lower() == transport.lower()]
    return filtered


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="List MCP servers from mcps/registry.yaml.")
    p.add_argument("--root", default=".", help="Repository root.")
    p.add_argument("--agent", help="Filter by allowed agent id.")
    p.add_argument("--status", choices=sorted(ALLOWED_MCP_STATUSES), help="Filter by MCP status.")
    p.add_argument("--transport", choices=sorted(ALLOWED_MCP_TRANSPORTS), help="Filter by transport.")
    p.add_argument("--json", action="store_true", help="Output JSON.")
    return p


def main() -> int:
    args = parser().parse_args()
    root = Path(args.root).resolve()
    try:
        registry = load_mcps_registry(root)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    mcps = filter_mcps(
        registry.get("mcps", []),
        agent=args.agent,
        status=args.status,
        transport=args.transport,
    )

    if args.json:
        print(json.dumps({"mcps": mcps}, indent=2, ensure_ascii=False))
        return 0

    if not mcps:
        print("No MCPs matched the filters.")
        return 0

    print("id                      name                         status     transport        secret  risk")
    print("----------------------  ---------------------------  ---------  ---------------  ------  -----")
    for mcp in mcps:
        print(
            f"{str(mcp.get('id', '')):<22}  "
            f"{str(mcp.get('name', '')):<27}  "
            f"{str(mcp.get('status', '')):<9}  "
            f"{str(mcp.get('transport', '')):<15}  "
            f"{str(mcp.get('requires_secret', '')):<6}  "
            f"{str(mcp.get('risk_level', ''))}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())