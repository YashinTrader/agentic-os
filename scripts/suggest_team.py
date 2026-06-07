#!/usr/bin/env python3
"""Deterministic team suggestion based on skills, labels, and task metadata."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml


def load_teams_registry(root: Path) -> dict[str, Any]:
    path = root / "teams" / "registry.yaml"
    if not path.exists():
        raise FileNotFoundError(f"{path.relative_to(root)} does not exist")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("teams/registry.yaml root must be a YAML mapping")
    return data


def load_task_file(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a YAML mapping")
    return data


def _normalize_tokens(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]*", text.lower())}


def _extract_task_context(task: dict[str, Any]) -> dict[str, Any]:
    labels = [str(x) for x in task.get("labels", []) if x]
    title = str(task.get("title", ""))
    objective = str(task.get("objective", ""))
    combined = f"{title} {objective}"
    tokens = _normalize_tokens(combined)
    inferred_skills: set[str] = set()
    if "dashboard" in tokens or "streamlit" in tokens or "kanban" in tokens:
        inferred_skills.add("build-streamlit-dashboard")
    if "cli" in tokens or "script" in tokens or "validator" in tokens or "python" in tokens:
        inferred_skills.add("implement-python-cli")
    if "protocol" in tokens or "schema" in tokens or "adr" in tokens or "review" in tokens:
        inferred_skills.add("review-protocol-change")
    if "log" in tokens or "handoff" in tokens or "summar" in tokens:
        inferred_skills.add("summarize-logs")
    return {
        "labels": labels,
        "keywords": tokens,
        "skills": inferred_skills,
        "risk_level": str(task.get("risk_level", "medium")).lower(),
        "title": title,
        "objective": objective,
    }


def score_team(
    team: dict[str, Any],
    *,
    desired_skills: set[str],
    labels: set[str],
    keywords: set[str],
    risk_level: str | None = None,
) -> dict[str, Any]:
    team_id = str(team.get("id", ""))
    required = {str(s) for s in team.get("required_skills", [])}
    optional = {str(s) for s in team.get("optional_skills", [])}
    suitability = team.get("task_suitability", {})
    if not isinstance(suitability, dict):
        suitability = {}

    suit_labels = {str(x).lower() for x in suitability.get("labels", [])}
    suit_keywords = {str(x).lower() for x in suitability.get("keywords", [])}
    suit_skills = {str(x) for x in suitability.get("skills", [])}
    suit_risks = {str(x).lower() for x in suitability.get("risk_levels", [])}

    matching_skills = sorted(desired_skills & (required | optional | suit_skills))
    missing_skills = sorted(required - desired_skills)

    score = 0
    score += 10 * len(desired_skills & required)
    score += 5 * len(desired_skills & optional)
    score += 8 * len(desired_skills & suit_skills)
    score += 3 * len(labels & suit_labels)
    score += 2 * len(keywords & suit_keywords)
    for kw in suit_keywords:
        if any(kw in token for token in keywords):
            score += 2
    if risk_level and risk_level in suit_risks:
        score += 2
    score -= 5 * len(missing_skills)

    status = str(team.get("status", "active"))
    if status == "planned":
        score -= 3
    elif status == "disabled":
        score -= 100

    default_reviewer = team.get("default_reviewer", {})
    reviewer_agent = default_reviewer.get("agent") if isinstance(default_reviewer, dict) else None

    notes_parts = []
    if missing_skills:
        notes_parts.append(f"Missing required skills: {', '.join(missing_skills)}")
    if status != "active":
        notes_parts.append(f"Team status is {status}")
    if not notes_parts:
        notes_parts.append("Good skill and keyword overlap")

    return {
        "team_id": team_id,
        "team_name": team.get("name", team_id),
        "score": score,
        "matching_skills": matching_skills,
        "missing_skills": missing_skills,
        "recommended_reviewer": reviewer_agent,
        "status": status,
        "notes": "; ".join(notes_parts),
    }


def suggest_teams(
    root: Path,
    *,
    task_path: Path | None = None,
    skill: str | None = None,
    label: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    registry = load_teams_registry(root)
    teams = [t for t in registry.get("teams", []) if isinstance(t, dict)]

    desired_skills: set[str] = set()
    labels: set[str] = set()
    keywords: set[str] = set()
    risk_level: str | None = None

    if skill:
        desired_skills.add(skill)
    if label:
        labels.add(label.lower())
        keywords.add(label.lower())

    if task_path:
        task = load_task_file(task_path)
        ctx = _extract_task_context(task)
        desired_skills |= ctx["skills"]
        labels |= {x.lower() for x in ctx["labels"]}
        keywords |= ctx["keywords"]
        risk_level = ctx["risk_level"]

    results = [
        score_team(
            team,
            desired_skills=desired_skills,
            labels=labels,
            keywords=keywords,
            risk_level=risk_level,
        )
        for team in teams
    ]
    results.sort(key=lambda x: (-x["score"], x["team_id"]))
    return results[:limit]


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Suggest suitable teams for a task or skill label.")
    p.add_argument("--root", default=".", help="Repository root.")
    p.add_argument("--task", help="Path to task YAML file.")
    p.add_argument("--skill", help="Skill id to match.")
    p.add_argument("--label", help="Label keyword to match.")
    p.add_argument("--json", action="store_true", help="Output JSON.")
    p.add_argument("--limit", type=int, default=5, help="Max suggestions to return.")
    return p


def main() -> int:
    args = parser().parse_args()
    root = Path(args.root).resolve()
    if not args.task and not args.skill and not args.label:
        print("Provide at least one of --task, --skill, or --label", file=sys.stderr)
        return 2

    task_path = Path(args.task).resolve() if args.task else None
    if task_path and not task_path.exists():
        print(f"Task file not found: {task_path}", file=sys.stderr)
        return 1

    try:
        suggestions = suggest_teams(
            root,
            task_path=task_path,
            skill=args.skill,
            label=args.label,
            limit=args.limit,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"suggestions": suggestions}, indent=2, ensure_ascii=False))
        return 0

    if not suggestions:
        print("No team suggestions.")
        return 0

    print("team_id               score  reviewer   matching_skills                    notes")
    print("--------------------  -----  ---------  -------------------------------  -----")
    for row in suggestions:
        skills = ", ".join(row["matching_skills"]) or "-"
        print(
            f"{row['team_id']:<20}  {row['score']:>5}  "
            f"{str(row.get('recommended_reviewer') or '-'):<9}  "
            f"{skills:<31}  {row['notes']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())