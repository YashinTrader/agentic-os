#!/usr/bin/env python3
"""List teams from teams/registry.yaml with optional filters."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ALLOWED_TEAM_STATUSES = {"active", "planned", "disabled"}


def load_teams_registry(root: Path) -> dict[str, Any]:
    path = root / "teams" / "registry.yaml"
    if not path.exists():
        raise FileNotFoundError(f"{path.relative_to(root)} does not exist")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("teams/registry.yaml root must be a YAML mapping")
    teams = data.get("teams", [])
    if not isinstance(teams, list):
        raise ValueError("teams/registry.yaml: teams must be a list")
    return data


def filter_teams(
    teams: list[dict[str, Any]],
    *,
    status: str | None = None,
    agent: str | None = None,
    skill: str | None = None,
) -> list[dict[str, Any]]:
    filtered = [t for t in teams if isinstance(t, dict)]
    if status:
        filtered = [t for t in filtered if str(t.get("status", "")).lower() == status.lower()]
    if agent:
        agent_lower = agent.lower()

        def team_has_agent(team: dict[str, Any]) -> bool:
            for member in team.get("members", []):
                if isinstance(member, dict) and str(member.get("agent", "")).lower() == agent_lower:
                    return True
            orch = team.get("orchestrator", {})
            if isinstance(orch, dict) and str(orch.get("agent", "")).lower() == agent_lower:
                return True
            return False

        filtered = [t for t in filtered if team_has_agent(t)]
    if skill:
        skill_lower = skill.lower()
        filtered = [
            t for t in filtered
            if skill_lower in [str(s).lower() for s in t.get("required_skills", [])]
            or skill_lower in [str(s).lower() for s in t.get("optional_skills", [])]
        ]
    return filtered


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="List teams from teams/registry.yaml.")
    p.add_argument("--root", default=".", help="Repository root.")
    p.add_argument("--status", choices=sorted(ALLOWED_TEAM_STATUSES), help="Filter by team status.")
    p.add_argument("--agent", help="Filter by member or orchestrator agent id.")
    p.add_argument("--skill", help="Filter by required or optional skill id.")
    p.add_argument("--json", action="store_true", help="Output JSON.")
    return p


def main() -> int:
    args = parser().parse_args()
    root = Path(args.root).resolve()
    try:
        registry = load_teams_registry(root)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    teams = filter_teams(
        registry.get("teams", []),
        status=args.status,
        agent=args.agent,
        skill=args.skill,
    )

    if args.json:
        print(json.dumps({"teams": teams}, indent=2, ensure_ascii=False))
        return 0

    if not teams:
        print("No teams matched the filters.")
        return 0

    print("id                  name                      status    orchestrator  members")
    print("------------------  ------------------------  --------  ------------  -------")
    for team in teams:
        orch = team.get("orchestrator", {})
        orch_agent = orch.get("agent", "-") if isinstance(orch, dict) else str(orch)
        member_count = len(team.get("members", []))
        print(
            f"{str(team.get('id', '')):<18}  "
            f"{str(team.get('name', '')):<24}  "
            f"{str(team.get('status', '')):<8}  "
            f"{str(orch_agent):<12}  "
            f"{member_count}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())