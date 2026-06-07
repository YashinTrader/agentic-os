"""LangGraph node implementations for orchestration planning."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from orchestrator.context_compiler import write_context_pack
from orchestrator.loaders import (
    collect_file_paths_from_task,
    load_events_for_task,
    load_handoffs_for_task,
    load_registry_list,
    load_task_yaml,
    load_team_by_id,
    normalize_tokens,
)
from orchestrator.persistence import run_dir, save_state
from orchestrator.planner import (
    build_recommended_prompt,
    build_verification_commands,
    write_plan,
)
from orchestrator.risk import evaluate_risk


def _repo_root(state: dict[str, Any]) -> Path:
    return Path(state["repo_root"]).resolve()


def _run_directory(state: dict[str, Any]) -> Path:
    return run_dir(_repo_root(state), state["run_id"], state.get("output_dir") or None)


def load_task(state: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    errors: list[str] = []
    try:
        task_path = Path(state["task_path"])
        task = load_task_yaml(task_path)
    except Exception as exc:
        return {"errors": [f"load_task failed: {exc}"]}

    for optional in ("labels", "acceptance", "constraints", "outputs"):
        if optional not in task or not task.get(optional):
            warnings.append(f"optional field missing or empty: {optional}")

    labels = [str(x) for x in task.get("labels", []) if x]
    acceptance = task.get("acceptance", task.get("acceptance_criteria", []))
    if isinstance(acceptance, str):
        acceptance = [acceptance]

    updates: dict[str, Any] = {
        "task_id": str(task.get("id", task_path.stem)),
        "title": str(task.get("title", "")),
        "objective": str(task.get("objective", task.get("context", ""))),
        "labels": labels,
        "risk_level": str(task.get("risk_level", "medium")).lower(),
        "approval_level": str(task.get("approval_level", "reviewer")),
        "status": str(task.get("status", "")),
        "owner": str(task.get("owner", "")),
        "task_data": task,
        "files_to_inspect": list(collect_file_paths_from_task(task)),
        "warnings": warnings,
        "events": [{"node": "load_task", "status": "ok"}],
    }
    if errors:
        updates["errors"] = errors
    return updates


def classify_task(state: dict[str, Any]) -> dict[str, Any]:
    task = state.get("task_data", {})
    repo = _repo_root(state)
    tokens = normalize_tokens(
        " ".join(
            [
                state.get("title", ""),
                state.get("objective", ""),
                " ".join(state.get("labels", [])),
                " ".join(str(x) for x in task.get("outputs", []) if x),
                " ".join(str(x) for x in task.get("inputs", []) if x),
            ]
        )
    )
    skills: set[str] = set()

    if {"dashboard", "streamlit", "kanban"} & tokens:
        skills.add("build-streamlit-dashboard")
    if {"cli", "script", "validator", "python", "orchestrator", "langgraph"} & tokens:
        skills.add("implement-python-cli")
    if {"protocol", "schema", "adr", "review", "registry"} & tokens:
        skills.add("review-protocol-change")
    if {"log", "handoff", "summar", "memory", "obsidian"} & tokens:
        skills.add("summarize-logs")

    for skill in load_registry_list(repo, "skills/registry.yaml", "skills"):
        sid = str(skill.get("id", ""))
        tags = {str(t).lower() for t in skill.get("tags", [])}
        if sid and (sid.replace("-", " ") in " ".join(tokens) or tags & tokens):
            skills.add(sid)

    files = collect_file_paths_from_task(task)
    if any("dashboard" in f for f in files):
        skills.add("build-streamlit-dashboard")
    if any("scripts/" in f for f in files):
        skills.add("implement-python-cli")

    return {
        "required_skills": sorted(skills),
        "events": [{"node": "classify_task", "skills": sorted(skills)}],
    }


def suggest_team(state: dict[str, Any]) -> dict[str, Any]:
    repo = _repo_root(state)
    scripts_dir = str(repo / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        from suggest_team import load_teams_registry, score_team
    except ImportError as exc:
        return {"errors": [f"suggest_team import failed: {exc}"]}

    registry = load_teams_registry(repo)
    teams = [t for t in registry.get("teams", []) if isinstance(t, dict)]
    desired_skills = {str(s) for s in state.get("required_skills", [])}
    labels = {str(x).lower() for x in state.get("labels", [])}
    keywords = normalize_tokens(f"{state.get('title', '')} {state.get('objective', '')}")
    candidates = [
        score_team(
            team,
            desired_skills=desired_skills,
            labels=labels,
            keywords=keywords,
            risk_level=state.get("risk_level"),
        )
        for team in teams
    ]
    candidates.sort(key=lambda x: (-x["score"], x["team_id"]))
    candidates = candidates[:5]
    if not candidates:
        return {"warnings": ["no candidate teams found"], "candidate_teams": []}

    top = candidates[0]
    team_id = str(top.get("team_id", ""))
    team = load_team_by_id(repo, team_id) or {}

    roles: list[str] = []
    agents: list[str] = []
    mcps: set[str] = set()
    for member in team.get("members", []):
        if isinstance(member, dict):
            role = str(member.get("role", ""))
            agent = str(member.get("agent", ""))
            if role:
                roles.append(role)
            if agent:
                agents.append(agent)
            for mcp in member.get("mcps", []):
                if isinstance(mcp, str):
                    mcps.add(mcp)
    for mcp in team.get("allowed_mcps", []):
        if isinstance(mcp, str):
            mcps.add(mcp)

    default_rev = team.get("default_reviewer", {})
    reviewer = default_rev.get("agent", top.get("recommended_reviewer", "claude")) if isinstance(default_rev, dict) else "claude"

    primary = ""
    for member in team.get("members", []):
        if isinstance(member, dict) and member.get("role") == "builder":
            primary = str(member.get("agent", ""))
            break
    if not primary and agents:
        primary = agents[0]

    orch = team.get("orchestrator", {})
    if isinstance(orch, dict) and orch.get("agent"):
        if str(orch["agent"]) not in agents:
            agents.insert(0, str(orch["agent"]))

    return {
        "candidate_teams": candidates,
        "selected_team": team_id,
        "selected_team_score": int(top.get("score", 0)),
        "selected_roles": sorted(set(roles)),
        "selected_agents": agents,
        "required_mcps": sorted(mcps),
        "recommended_primary_agent": primary or "composer",
        "recommended_reviewer": str(reviewer),
        "events": [{"node": "suggest_team", "selected_team": team_id}],
    }


def compile_context(state: dict[str, Any]) -> dict[str, Any]:
    repo = _repo_root(state)
    task_id = state.get("task_id", "")
    handoffs = load_handoffs_for_task(repo, task_id)
    events = load_events_for_task(repo, task_id)

    enriched = dict(state)
    enriched["recent_handoffs"] = handoffs
    enriched["recent_events"] = events
    enriched["recommended_prompt"] = build_recommended_prompt(enriched)
    enriched["verification_commands"] = build_verification_commands()

    rd = _run_directory(state)
    md_path, json_path = write_context_pack(rd, enriched, bool(state.get("dry_run")))

    return {
        "context_pack_path": md_path,
        "context_pack_json_path": json_path,
        "recommended_prompt": enriched["recommended_prompt"],
        "verification_commands": enriched["verification_commands"],
        "recent_handoffs": handoffs,
        "recent_events": events,
        "events": [{"node": "compile_context", "context_pack_path": md_path}],
    }


def risk_gate(state: dict[str, Any]) -> dict[str, Any]:
    result = evaluate_risk(state.get("task_data", {}), state)
    next_action = "await_human_approval" if result["approval_level"] == "human" else (
        "request_reviewer_signoff" if result["approval_required"] else "dispatch_to_primary_agent_when_execution_enabled"
    )
    return {
        "approval_required": result["approval_required"],
        "approval_level": result["approval_level"],
        "approval_reason": result["approval_reason"],
        "next_action": next_action,
        "events": [{"node": "risk_gate", "approval_level": result["approval_level"]}],
    }


def generate_plan(state: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(state)
    if not enriched.get("recommended_prompt"):
        enriched["recommended_prompt"] = build_recommended_prompt(enriched)
    if not enriched.get("verification_commands"):
        enriched["verification_commands"] = build_verification_commands()

    rd = _run_directory(state)
    md_path, json_path = write_plan(rd, enriched, bool(state.get("dry_run")))
    return {
        "plan_path": md_path,
        "plan_json_path": json_path,
        "recommended_prompt": enriched["recommended_prompt"],
        "events": [{"node": "generate_plan", "plan_path": md_path}],
    }


def finalize(state: dict[str, Any]) -> dict[str, Any]:
    from orchestrator.persistence import append_orchestration_event, save_latest
    from orchestrator.planner import generate_plan_dict

    repo = _repo_root(state)
    rd = _run_directory(state)
    dry_run = bool(state.get("dry_run"))

    save_state(rd, state, dry_run)
    plan = generate_plan_dict(state)
    latest_state_path, latest_plan_path = save_latest(repo, state, plan, dry_run)
    append_orchestration_event(repo, state, dry_run, bool(state.get("no_log")))

    return {
        "events": [{"node": "finalize", "latest_state": latest_state_path, "latest_plan": latest_plan_path}],
    }