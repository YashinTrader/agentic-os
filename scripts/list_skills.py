#!/usr/bin/env python3
"""List skills from skills/registry.yaml with optional filters."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

SKILL_REQUIRED_FIELDS = {
    "id",
    "name",
    "version",
    "description",
    "category",
    "allowed_agents",
    "required_clis",
    "required_mcps",
    "required_files",
    "outputs",
    "risk_level",
    "approval_level",
    "tags",
    "status",
    "notes",
}

ALLOWED_SKILL_RISK_LEVELS = {"low", "medium", "high"}
ALLOWED_SKILL_APPROVAL_LEVELS = {"none", "reviewer", "human", "blocked"}


def load_skills_registry(root: Path) -> dict[str, Any]:
    path = root / "skills" / "registry.yaml"
    if not path.exists():
        raise FileNotFoundError(f"{path.relative_to(root)} does not exist")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("skills/registry.yaml root must be a YAML mapping")
    skills = data.get("skills", [])
    if not isinstance(skills, list):
        raise ValueError("skills/registry.yaml: skills must be a list")
    return data


def filter_skills(
    skills: list[dict[str, Any]],
    *,
    agent: str | None = None,
    risk: str | None = None,
    approval: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    filtered = [s for s in skills if isinstance(s, dict)]
    if agent:
        agent_lower = agent.lower()
        filtered = [
            s for s in filtered
            if any(agent_lower == str(a).lower() for a in s.get("allowed_agents", []))
        ]
    if risk:
        filtered = [s for s in filtered if str(s.get("risk_level", "")).lower() == risk.lower()]
    if approval:
        filtered = [s for s in filtered if str(s.get("approval_level", "")).lower() == approval.lower()]
    if category:
        filtered = [s for s in filtered if str(s.get("category", "")).lower() == category.lower()]
    return filtered


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="List skills from skills/registry.yaml.")
    p.add_argument("--root", default=".", help="Repository root.")
    p.add_argument("--agent", help="Filter by allowed agent id.")
    p.add_argument("--risk", choices=sorted(ALLOWED_SKILL_RISK_LEVELS), help="Filter by risk level.")
    p.add_argument("--approval", choices=sorted(ALLOWED_SKILL_APPROVAL_LEVELS), help="Filter by approval level.")
    p.add_argument("--category", help="Filter by category.")
    p.add_argument("--json", action="store_true", help="Output JSON.")
    return p


def main() -> int:
    args = parser().parse_args()
    root = Path(args.root).resolve()
    try:
        registry = load_skills_registry(root)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    skills = filter_skills(
        registry.get("skills", []),
        agent=args.agent,
        risk=args.risk,
        approval=args.approval,
        category=args.category,
    )

    if args.json:
        print(json.dumps({"skills": skills}, indent=2, ensure_ascii=False))
        return 0

    if not skills:
        print("No skills matched the filters.")
        return 0

    print("id                      name                         risk     approval   agents")
    print("----------------------  ---------------------------  -------  ---------  ------")
    for skill in skills:
        agents = ", ".join(skill.get("allowed_agents", []))
        print(
            f"{str(skill.get('id', '')):<22}  "
            f"{str(skill.get('name', '')):<27}  "
            f"{str(skill.get('risk_level', '')):<7}  "
            f"{str(skill.get('approval_level', '')):<9}  "
            f"{agents}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())