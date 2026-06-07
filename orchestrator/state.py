"""Orchestrator state schema — JSON-serializable planning state."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class OrchestratorState:
    run_id: str = ""
    task_id: str = ""
    task_path: str = ""
    title: str = ""
    objective: str = ""
    labels: list[str] = field(default_factory=list)
    risk_level: str = "medium"
    approval_level: str = "reviewer"
    status: str = ""
    owner: str = ""
    required_skills: list[str] = field(default_factory=list)
    candidate_teams: list[dict[str, Any]] = field(default_factory=list)
    selected_team: str = ""
    selected_team_score: int = 0
    selected_roles: list[str] = field(default_factory=list)
    selected_agents: list[str] = field(default_factory=list)
    required_mcps: list[str] = field(default_factory=list)
    context_pack_path: str = ""
    plan_path: str = ""
    approval_required: bool = False
    approval_reason: str = ""
    next_action: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    repo_root: str = ""
    output_dir: str = ""
    dry_run: bool = False
    no_log: bool = False
    task_data: dict[str, Any] = field(default_factory=dict)
    context_pack_json_path: str = ""
    plan_json_path: str = ""
    recommended_primary_agent: str = ""
    recommended_reviewer: str = ""
    verification_commands: list[str] = field(default_factory=list)
    files_to_inspect: list[str] = field(default_factory=list)
    recommended_prompt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        from orchestrator.persistence import _json_safe

        return json.dumps(_json_safe(self.to_dict()), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OrchestratorState:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


def state_to_graph_dict(state: OrchestratorState) -> dict[str, Any]:
    return state.to_dict()


def graph_dict_to_state(data: dict[str, Any]) -> OrchestratorState:
    return OrchestratorState.from_dict(data)


def merge_state(state: OrchestratorState, updates: dict[str, Any]) -> OrchestratorState:
    current = state.to_dict()
    for key, value in updates.items():
        if key in ("errors", "warnings", "events") and isinstance(value, list):
            current[key] = list(current.get(key, [])) + value
        else:
            current[key] = value
    return OrchestratorState.from_dict(current)