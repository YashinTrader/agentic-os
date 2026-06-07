"""Generate orchestration plans from state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_recommended_prompt(state: dict[str, Any]) -> str:
    task_id = state.get("task_id", "")
    team = state.get("selected_team", "")
    agent = state.get("recommended_primary_agent", "composer")
    skills = ", ".join(state.get("required_skills", []))
    return (
        f"You are the {agent} agent on team '{team}' for task {task_id}.\n"
        f"Objective: {state.get('objective', '')}\n"
        f"Required skills: {skills or 'general implementation'}.\n"
        f"Read the context pack at runtime/orchestrator/runs/{state.get('run_id', '')}/context_pack.md.\n"
        f"Follow docs/AGENT_PROTOCOL.md. Do not merge to main. Write a handoff when done.\n"
        f"Verification: python -m unittest && python scripts/validate.py"
    )


def build_verification_commands() -> list[str]:
    return [
        "python -m unittest",
        "python scripts/validate.py",
    ]


def generate_plan_dict(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": state.get("run_id"),
        "task_id": state.get("task_id"),
        "task_summary": {
            "title": state.get("title"),
            "status": state.get("status"),
            "owner": state.get("owner"),
            "risk_level": state.get("risk_level"),
        },
        "selected_team": state.get("selected_team"),
        "selected_team_score": state.get("selected_team_score"),
        "recommended_primary_agent": state.get("recommended_primary_agent"),
        "recommended_reviewer": state.get("recommended_reviewer"),
        "selected_roles": state.get("selected_roles", []),
        "selected_agents": state.get("selected_agents", []),
        "required_skills": state.get("required_skills", []),
        "required_mcps": state.get("required_mcps", []),
        "approval_level": state.get("approval_level"),
        "approval_required": state.get("approval_required"),
        "approval_reason": state.get("approval_reason"),
        "risk_notes": state.get("warnings", []),
        "recommended_prompt": state.get("recommended_prompt"),
        "verification_commands": state.get("verification_commands", []),
        "files_to_inspect": state.get("files_to_inspect", []),
        "next_action": state.get("next_action"),
        "executed_automatically": False,
        "statement": "This plan is advisory only. No agents were launched.",
    }


def generate_plan_markdown(state: dict[str, Any]) -> str:
    plan = generate_plan_dict(state)
    cmds = "\n".join(f"- `{c}`" for c in plan.get("verification_commands", []))
    files = "\n".join(f"- `{f}`" for f in plan.get("files_to_inspect", []))
    return f"""# Orchestration Plan: {plan['task_id']}

## Task Summary
- **Title:** {plan['task_summary']['title']}
- **Status:** {plan['task_summary']['status']}
- **Owner:** {plan['task_summary']['owner']}
- **Risk:** {plan['task_summary']['risk_level']}

## Team Selection
- **Team:** [[{plan['selected_team']}]] (score {plan['selected_team_score']})
- **Primary agent:** {plan['recommended_primary_agent']}
- **Reviewer:** {plan['recommended_reviewer']}
- **Roles:** {', '.join(plan['selected_roles']) or '—'}
- **Agents:** {', '.join(plan['selected_agents']) or '—'}

## Requirements
- **Skills:** {', '.join(plan['required_skills']) or '—'}
- **MCPs:** {', '.join(plan['required_mcps']) or '—'}

## Approval
- **Required:** {plan['approval_required']}
- **Level:** {plan['approval_level']}
- **Reason:** {plan['approval_reason']}

## Suggested Next Prompt
```
{plan['recommended_prompt']}
```

## Verification Commands
{cmds or '- (none)'}

## Files To Inspect
{files or '- (none)'}

## Next Action
{plan['next_action']}

---
**{plan['statement']}**
"""


def write_plan(run_dir: Path, state: dict[str, Any], dry_run: bool) -> tuple[str, str]:
    plan = generate_plan_dict(state)
    md = generate_plan_markdown(state)
    md_path = run_dir / "plan.md"
    json_path = run_dir / "plan.json"
    if not dry_run:
        run_dir.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md, encoding="utf-8")
        json_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(md_path), str(json_path)