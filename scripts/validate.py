#!/usr/bin/env python3
"""Validate the Agentic OS file coordination skeleton."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only without dependency.
    print("PyYAML is required. Install with: python -m pip install -r requirements.txt", file=sys.stderr)
    sys.exit(2)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from protocol.event_types import ALLOWED_EVENT_TYPES, V1_ALLOWED_EVENTS  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]

RENAMES = {
    "created": "created_at",
    "updated": "updated_at",
    "acceptance_criteria": "acceptance",
    "handoff_notes": "notes",
}

V2_REQUIRED_TASK_FIELDS = {
    "id",
    "title",
    "owner",
    "status",
    "created_at",
    "updated_at",
    "objective",
    "inputs",
    "outputs",
    "constraints",
    "acceptance",
    "notes",
    "risk_level",
    "requires_human_approval",
    "reviewer",
    "created_by",
    "phase",
    "goals",
    "non_goals",
    "priority",
}

ALLOWED_STATUSES = {"ready", "todo", "in_progress", "review", "blocked", "done"}
ALLOWED_RISK_LEVELS = {"low", "medium", "high"}
ALLOWED_PRIORITIES = {"high", "medium", "low", "P0", "P1", "P2", "P3"}
LIST_FIELDS = {
    "inputs",
    "outputs",
    "constraints",
    "acceptance",
    "acceptance_criteria",
    "goals",
    "non_goals",
    "human_approval_checklist",
}

REQUIRED_HANDOFF_SECTIONS = [
    "## What I Did",
    "## What Remains",
    "## Decisions Made",
    "## Open Questions",
    "## How to Verify My Work",
    "## Risks / Caveats",
    "## Recommended Next Action for Receiver",
]

from scripts.repository_verification import (  # noqa: E402
    REQUIRED_VERIFICATION_FIELDS_V2 as REQUIRED_VERIFICATION_FIELDS,
    validate_handoff_verification_block,
)

REQUIRED_ADR_SECTIONS = [
    "## Context",
    "## Decision",
    "## Consequences",
]

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
ALLOWED_SKILL_APPROVAL_LEVELS = {"none", "reviewer", "human", "blocked"}
ALLOWED_SKILL_STATUSES = {"active", "planned", "deprecated", "disabled"}
SKILL_LIST_FIELDS = {"allowed_agents", "required_clis", "required_mcps", "required_files", "outputs", "tags"}

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
ALLOWED_MCP_APPROVAL_LEVELS = {"none", "reviewer", "human", "blocked"}
MCP_LIST_FIELDS = {"args", "env_vars_required", "allowed_agents", "capabilities"}

ROLE_REQUIRED_FIELDS = {
    "id",
    "name",
    "description",
    "responsibilities",
    "allowed_agents",
    "required_skills",
    "optional_skills",
    "allowed_mcps",
    "risk_level",
    "approval_level",
    "can_delegate",
    "can_review",
    "can_execute",
    "notes",
}
ROLE_LIST_FIELDS = {
    "responsibilities",
    "allowed_agents",
    "required_skills",
    "optional_skills",
    "allowed_mcps",
}
ALLOWED_ROLE_APPROVAL_LEVELS = {"none", "reviewer", "human", "blocked"}

TEAM_REQUIRED_FIELDS = {
    "id",
    "name",
    "description",
    "purpose",
    "orchestrator",
    "members",
    "default_reviewer",
    "required_skills",
    "optional_skills",
    "allowed_mcps",
    "approval_policy",
    "task_suitability",
    "status",
    "notes",
}
TEAM_MEMBER_REQUIRED_FIELDS = {"agent", "role", "skills", "mcps", "priority", "notes"}
TEAM_LIST_FIELDS = {"required_skills", "optional_skills", "allowed_mcps"}
ALLOWED_TEAM_STATUSES = {"active", "planned", "disabled"}


def task_files() -> list[Path]:
    paths: list[Path] = []
    for directory in ("tasks/active", "tasks/done", "tasks/blocked"):
        paths.extend(sorted((ROOT / directory).glob("*.yaml")))
        paths.extend(sorted((ROOT / directory).glob("*.yml")))
    return paths


def canonical_task(data: dict[str, Any]) -> dict[str, Any]:
    canonical = dict(data)
    for old, new in RENAMES.items():
        if old in canonical and new not in canonical:
            canonical[new] = canonical[old]
    return canonical


def validate_tasks(errors: list[str], warnings: list[str]) -> None:
    for path in task_files():
        rel = path.relative_to(ROOT)
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{rel}: invalid YAML: {exc}")
            continue

        if not isinstance(data, dict):
            errors.append(f"{rel}: task file must contain a YAML mapping")
            continue

        for old, new in RENAMES.items():
            if old in data and new in data:
                errors.append(f"{rel}: contains both {old!r} and {new!r}; choose schema v2 field {new!r}")
            elif old in data:
                warnings.append(f"{rel}: uses deprecated v1 field {old!r}; rename to {new!r}")

        canonical = canonical_task(data)
        missing = sorted(V2_REQUIRED_TASK_FIELDS - set(canonical))
        if missing:
            errors.append(f"{rel}: missing required fields: {', '.join(missing)}")

        status = canonical.get("status")
        if status not in ALLOWED_STATUSES:
            errors.append(f"{rel}: invalid status {status!r}; expected one of {sorted(ALLOWED_STATUSES)}")
        elif status == "todo":
            warnings.append(f"{rel}: status 'todo' is deprecated; use 'ready'")

        risk_level = canonical.get("risk_level")
        if risk_level not in ALLOWED_RISK_LEVELS:
            errors.append(f"{rel}: invalid risk_level {risk_level!r}; expected one of {sorted(ALLOWED_RISK_LEVELS)}")

        priority = canonical.get("priority")
        if priority not in ALLOWED_PRIORITIES:
            errors.append(f"{rel}: invalid priority {priority!r}; expected high, medium, low")
        elif isinstance(priority, str) and priority.startswith("P"):
            warnings.append(f"{rel}: priority {priority!r} is deprecated; use high, medium, or low")

        if not isinstance(canonical.get("requires_human_approval"), bool):
            errors.append(f"{rel}: requires_human_approval must be a boolean")

        if status in {"review", "done"} and not canonical.get("reviewer"):
            errors.append(f"{rel}: reviewer is required when status is review or done")
        if canonical.get("reviewer") and canonical.get("reviewer") == canonical.get("owner"):
            errors.append(f"{rel}: reviewer must differ from owner")

        checklist = canonical.get("human_approval_checklist")
        if canonical.get("requires_human_approval") and not checklist:
            errors.append(f"{rel}: requires_human_approval is true but human_approval_checklist is empty")

        for list_field in LIST_FIELDS:
            if list_field in canonical and not isinstance(canonical[list_field], list):
                errors.append(f"{rel}: {list_field} must be a list")


def validate_logs(errors: list[str], warnings: list[str]) -> None:
    path = ROOT / "logs" / "agent-events.jsonl"
    if not path.exists():
        errors.append("logs/agent-events.jsonl: file does not exist")
        return

    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        errors.append("logs/agent-events.jsonl: file must contain at least one event")
        return

    for index, line in enumerate(lines, start=1):
        if not line.strip():
            errors.append(f"logs/agent-events.jsonl:{index}: blank lines are not valid JSONL events")
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"logs/agent-events.jsonl:{index}: invalid JSON: {exc}")
            continue
        if not isinstance(event, dict):
            errors.append(f"logs/agent-events.jsonl:{index}: event must be a JSON object")
            continue

        base_missing = sorted({"ts", "agent"} - set(event))
        if base_missing:
            errors.append(f"logs/agent-events.jsonl:{index}: missing required fields: {', '.join(base_missing)}")

        if "type" in event and "event" in event:
            errors.append(f"logs/agent-events.jsonl:{index}: contains both 'type' and deprecated 'event'")
        elif "type" in event:
            if event["type"] not in ALLOWED_EVENT_TYPES:
                errors.append(f"logs/agent-events.jsonl:{index}: unknown event type {event['type']!r}")
        elif "event" in event:
            warnings.append(f"logs/agent-events.jsonl:{index}: uses deprecated v1 field 'event'; use 'type'")
            if event["event"] not in V1_ALLOWED_EVENTS:
                warnings.append(f"logs/agent-events.jsonl:{index}: unknown v1 event {event['event']!r}")
        else:
            errors.append(f"logs/agent-events.jsonl:{index}: missing required field 'type'")


def validate_handoffs(errors: list[str]) -> None:
    for path in sorted((ROOT / "handoffs").glob("*.md")):
        if path.name == "README.md":
            continue
        rel = str(path.relative_to(ROOT))
        text = path.read_text(encoding="utf-8")
        if not text.startswith("# Handoff: "):
            errors.append(f"{rel}: must start with '# Handoff: <task-id>'")
        for marker in ("**From:**", "**To:**", "**Date:**", "**Task Status After Handoff:**"):
            if marker not in text:
                errors.append(f"{rel}: missing metadata marker {marker}")
        for section in REQUIRED_HANDOFF_SECTIONS:
            if section not in text:
                errors.append(f"{rel}: missing required section {section}")
        validate_handoff_verification_block(rel, text, errors)


def has_adr_metadata(text: str, key: str) -> bool:
    lower_key = key.lower()
    for line in text.splitlines()[:12]:
        normalized = line.strip().lstrip("-").strip().lstrip("*").lower()
        if normalized.startswith(lower_key):
            return True
    return False


def validate_adrs(errors: list[str]) -> None:
    for path in sorted((ROOT / "decisions").glob("ADR-*.md")):
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        if not text.startswith("# ADR-"):
            errors.append(f"{rel}: must start with '# ADR-####: <title>'")
        for key in ("status:", "date:"):
            if not has_adr_metadata(text, key):
                errors.append(f"{rel}: missing metadata key {key}")
        for section in REQUIRED_ADR_SECTIONS:
            if section not in text:
                errors.append(f"{rel}: missing required section {section}")


def validate_skills_registry(errors: list[str]) -> None:
    path = ROOT / "skills" / "registry.yaml"
    rel = path.relative_to(ROOT)
    if not path.exists():
        errors.append(f"{rel}: file does not exist")
        return
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{rel}: invalid YAML: {exc}")
        return
    if not isinstance(data, dict):
        errors.append(f"{rel}: root must be a YAML mapping")
        return
    skills = data.get("skills")
    if not isinstance(skills, list):
        errors.append(f"{rel}: skills must be a list")
        return
    if not skills:
        errors.append(f"{rel}: skills must contain at least one entry")
        return

    seen_ids: set[str] = set()
    for index, skill in enumerate(skills, start=1):
        prefix = f"{rel}:skills[{index}]"
        if not isinstance(skill, dict):
            errors.append(f"{prefix}: skill entry must be a mapping")
            continue
        skill_id = skill.get("id")
        if not isinstance(skill_id, str) or not skill_id.strip():
            errors.append(f"{prefix}: id must be a non-empty string")
        elif skill_id in seen_ids:
            errors.append(f"{prefix}: duplicate skill id {skill_id!r}")
        else:
            seen_ids.add(skill_id)

        missing = sorted(SKILL_REQUIRED_FIELDS - set(skill))
        if missing:
            errors.append(f"{prefix} ({skill_id or 'unknown'}): missing required fields: {', '.join(missing)}")

        risk_level = skill.get("risk_level")
        if risk_level not in ALLOWED_RISK_LEVELS:
            errors.append(f"{prefix} ({skill_id}): invalid risk_level {risk_level!r}")

        approval_level = skill.get("approval_level")
        if approval_level not in ALLOWED_SKILL_APPROVAL_LEVELS:
            errors.append(f"{prefix} ({skill_id}): invalid approval_level {approval_level!r}")

        skill_status = skill.get("status")
        if skill_status not in ALLOWED_SKILL_STATUSES:
            errors.append(f"{prefix} ({skill_id}): invalid status {skill_status!r}")

        for list_field in SKILL_LIST_FIELDS:
            if list_field in skill and not isinstance(skill[list_field], list):
                errors.append(f"{prefix} ({skill_id}): {list_field} must be a list")


def validate_mcps_registry(errors: list[str]) -> None:
    path = ROOT / "mcps" / "registry.yaml"
    rel = path.relative_to(ROOT)
    if not path.exists():
        errors.append(f"{rel}: file does not exist")
        return
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{rel}: invalid YAML: {exc}")
        return
    if not isinstance(data, dict):
        errors.append(f"{rel}: root must be a YAML mapping")
        return
    mcps = data.get("mcps")
    if not isinstance(mcps, list):
        errors.append(f"{rel}: mcps must be a list")
        return
    if not mcps:
        errors.append(f"{rel}: mcps must contain at least one entry")
        return

    seen_ids: set[str] = set()
    for index, mcp in enumerate(mcps, start=1):
        prefix = f"{rel}:mcps[{index}]"
        if not isinstance(mcp, dict):
            errors.append(f"{prefix}: MCP entry must be a mapping")
            continue
        mcp_id = mcp.get("id")
        if not isinstance(mcp_id, str) or not mcp_id.strip():
            errors.append(f"{prefix}: id must be a non-empty string")
        elif mcp_id in seen_ids:
            errors.append(f"{prefix}: duplicate MCP id {mcp_id!r}")
        else:
            seen_ids.add(mcp_id)

        missing = sorted(MCP_REQUIRED_FIELDS - set(mcp))
        if missing:
            errors.append(f"{prefix} ({mcp_id or 'unknown'}): missing required fields: {', '.join(missing)}")

        status = mcp.get("status")
        if status not in ALLOWED_MCP_STATUSES:
            errors.append(f"{prefix} ({mcp_id}): invalid status {status!r}")

        transport = mcp.get("transport")
        if transport not in ALLOWED_MCP_TRANSPORTS:
            errors.append(f"{prefix} ({mcp_id}): invalid transport {transport!r}")

        if not isinstance(mcp.get("requires_secret"), bool):
            errors.append(f"{prefix} ({mcp_id}): requires_secret must be a boolean")

        risk_level = mcp.get("risk_level")
        if risk_level not in ALLOWED_RISK_LEVELS:
            errors.append(f"{prefix} ({mcp_id}): invalid risk_level {risk_level!r}")

        approval_level = mcp.get("approval_level")
        if approval_level not in ALLOWED_MCP_APPROVAL_LEVELS:
            errors.append(f"{prefix} ({mcp_id}): invalid approval_level {approval_level!r}")

        for list_field in MCP_LIST_FIELDS:
            if list_field in mcp and not isinstance(mcp[list_field], list):
                errors.append(f"{prefix} ({mcp_id}): {list_field} must be a list")

        if status == "planned" and mcp.get("command") is not None:
            errors.append(f"{prefix} ({mcp_id}): planned MCPs must have command: null")
        if status == "planned" and mcp.get("endpoint") is not None:
            errors.append(f"{prefix} ({mcp_id}): planned MCPs must have endpoint: null")


def _load_registry_ids(path: Path, key: str) -> set[str]:
    if not path.exists():
        return set()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(data, dict):
        return set()
    return {
        item.get("id")
        for item in data.get(key, [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def _validate_agent_ref(
    errors: list[str],
    prefix: str,
    ref: Any,
    field_name: str,
    member_agents: set[str],
) -> None:
    if not isinstance(ref, dict):
        errors.append(f"{prefix}: {field_name} must be a mapping with agent and external")
        return
    agent = ref.get("agent")
    external = ref.get("external")
    if not isinstance(agent, str) or not agent.strip():
        errors.append(f"{prefix}: {field_name}.agent must be a non-empty string")
        return
    if not isinstance(external, bool):
        errors.append(f"{prefix}: {field_name}.external must be a boolean")
        return
    if not external and agent not in member_agents:
        errors.append(
            f"{prefix}: {field_name}.agent {agent!r} must appear in members or external must be true"
        )


def _validate_skill_refs(
    errors: list[str],
    prefix: str,
    skill_ids: set[str],
    refs: Any,
    field_name: str,
) -> None:
    if not isinstance(refs, list):
        return
    for ref in refs:
        if isinstance(ref, str) and ref not in skill_ids:
            errors.append(f"{prefix}: {field_name} references unknown skill id {ref!r}")


def _validate_mcp_refs(
    errors: list[str],
    prefix: str,
    mcp_ids: set[str],
    refs: Any,
    field_name: str,
) -> None:
    if not isinstance(refs, list):
        return
    for ref in refs:
        if isinstance(ref, str) and ref and ref not in mcp_ids:
            errors.append(f"{prefix}: {field_name} references unknown MCP id {ref!r}")


def validate_roles_registry(errors: list[str], skill_ids: set[str], mcp_ids: set[str]) -> set[str]:
    path = ROOT / "roles" / "registry.yaml"
    rel = path.relative_to(ROOT)
    role_ids: set[str] = set()
    if not path.exists():
        errors.append(f"{rel}: file does not exist")
        return role_ids
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{rel}: invalid YAML: {exc}")
        return role_ids
    if not isinstance(data, dict):
        errors.append(f"{rel}: root must be a YAML mapping")
        return role_ids
    roles = data.get("roles")
    if not isinstance(roles, list):
        errors.append(f"{rel}: roles must be a list")
        return role_ids
    if not roles:
        errors.append(f"{rel}: roles must contain at least one entry")
        return role_ids

    seen_ids: set[str] = set()
    for index, role in enumerate(roles, start=1):
        prefix = f"{rel}:roles[{index}]"
        if not isinstance(role, dict):
            errors.append(f"{prefix}: role entry must be a mapping")
            continue
        role_id = role.get("id")
        if not isinstance(role_id, str) or not role_id.strip():
            errors.append(f"{prefix}: id must be a non-empty string")
        elif role_id in seen_ids:
            errors.append(f"{prefix}: duplicate role id {role_id!r}")
        else:
            seen_ids.add(role_id)
            role_ids.add(role_id)

        missing = sorted(ROLE_REQUIRED_FIELDS - set(role))
        if missing:
            errors.append(f"{prefix} ({role_id or 'unknown'}): missing required fields: {', '.join(missing)}")

        if role.get("risk_level") not in ALLOWED_RISK_LEVELS:
            errors.append(f"{prefix} ({role_id}): invalid risk_level {role.get('risk_level')!r}")
        if role.get("approval_level") not in ALLOWED_ROLE_APPROVAL_LEVELS:
            errors.append(f"{prefix} ({role_id}): invalid approval_level {role.get('approval_level')!r}")

        for flag in ("can_delegate", "can_review", "can_execute"):
            if not isinstance(role.get(flag), bool):
                errors.append(f"{prefix} ({role_id}): {flag} must be a boolean")

        for list_field in ROLE_LIST_FIELDS:
            if list_field in role and not isinstance(role[list_field], list):
                errors.append(f"{prefix} ({role_id}): {list_field} must be a list")

        _validate_skill_refs(errors, prefix, skill_ids, role.get("required_skills"), "required_skills")
        _validate_skill_refs(errors, prefix, skill_ids, role.get("optional_skills"), "optional_skills")
        _validate_mcp_refs(errors, prefix, mcp_ids, role.get("allowed_mcps"), "allowed_mcps")

    return role_ids


def validate_teams_registry(
    errors: list[str],
    skill_ids: set[str],
    mcp_ids: set[str],
    role_ids: set[str],
) -> None:
    path = ROOT / "teams" / "registry.yaml"
    rel = path.relative_to(ROOT)
    if not path.exists():
        errors.append(f"{rel}: file does not exist")
        return
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{rel}: invalid YAML: {exc}")
        return
    if not isinstance(data, dict):
        errors.append(f"{rel}: root must be a YAML mapping")
        return
    teams = data.get("teams")
    if not isinstance(teams, list):
        errors.append(f"{rel}: teams must be a list")
        return
    if not teams:
        errors.append(f"{rel}: teams must contain at least one entry")
        return

    seen_ids: set[str] = set()
    for index, team in enumerate(teams, start=1):
        prefix = f"{rel}:teams[{index}]"
        if not isinstance(team, dict):
            errors.append(f"{prefix}: team entry must be a mapping")
            continue
        team_id = team.get("id")
        if not isinstance(team_id, str) or not team_id.strip():
            errors.append(f"{prefix}: id must be a non-empty string")
        elif team_id in seen_ids:
            errors.append(f"{prefix}: duplicate team id {team_id!r}")
        else:
            seen_ids.add(team_id)

        missing = sorted(TEAM_REQUIRED_FIELDS - set(team))
        if missing:
            errors.append(f"{prefix} ({team_id or 'unknown'}): missing required fields: {', '.join(missing)}")

        status = team.get("status")
        if status not in ALLOWED_TEAM_STATUSES:
            errors.append(f"{prefix} ({team_id}): invalid status {status!r}")

        for list_field in TEAM_LIST_FIELDS:
            if list_field in team and not isinstance(team[list_field], list):
                errors.append(f"{prefix} ({team_id}): {list_field} must be a list")

        _validate_skill_refs(errors, prefix, skill_ids, team.get("required_skills"), "required_skills")
        _validate_skill_refs(errors, prefix, skill_ids, team.get("optional_skills"), "optional_skills")
        _validate_mcp_refs(errors, prefix, mcp_ids, team.get("allowed_mcps"), "allowed_mcps")

        members = team.get("members", [])
        if not isinstance(members, list) or not members:
            errors.append(f"{prefix} ({team_id}): members must be a non-empty list")
            member_agents: set[str] = set()
        else:
            member_agents = set()
            for m_index, member in enumerate(members, start=1):
                m_prefix = f"{prefix}:members[{m_index}]"
                if not isinstance(member, dict):
                    errors.append(f"{m_prefix}: member must be a mapping")
                    continue
                m_missing = sorted(TEAM_MEMBER_REQUIRED_FIELDS - set(member))
                if m_missing:
                    errors.append(f"{m_prefix}: missing required fields: {', '.join(m_missing)}")
                agent = member.get("agent")
                role = member.get("role")
                if isinstance(agent, str):
                    member_agents.add(agent)
                if isinstance(role, str) and role not in role_ids:
                    errors.append(f"{m_prefix}: role {role!r} not found in roles/registry.yaml")
                if not isinstance(member.get("priority"), int):
                    errors.append(f"{m_prefix}: priority must be an integer")
                if not isinstance(member.get("skills"), list):
                    errors.append(f"{m_prefix}: skills must be a list")
                else:
                    _validate_skill_refs(errors, m_prefix, skill_ids, member.get("skills"), "skills")
                if not isinstance(member.get("mcps"), list):
                    errors.append(f"{m_prefix}: mcps must be a list")
                else:
                    _validate_mcp_refs(errors, m_prefix, mcp_ids, member.get("mcps"), "mcps")

        _validate_agent_ref(errors, prefix, team.get("orchestrator"), "orchestrator", member_agents)
        _validate_agent_ref(errors, prefix, team.get("default_reviewer"), "default_reviewer", member_agents)

        policy = team.get("approval_policy")
        if not isinstance(policy, dict):
            errors.append(f"{prefix} ({team_id}): approval_policy must be a mapping")


OBSIDIAN_MAPPING_REQUIRED_FIELDS = {
    "vault_path",
    "project_name",
    "sync_enabled",
    "dry_run_default",
    "vault_root_folder",
    "output_folders",
    "include_sections",
    "exclude_patterns",
    "last_sync_file",
}


PHASE_2_REVIEW_REQUIRED_FILES = {
    "docs/PHASE_2_REVIEW_PACKET.md": [
        "## A. Phase 2.0",
        "## B. Phase 2.1",
        "## C. Phase 2.2",
        "## D. Phase 2.3",
        "## E. Phase 2.4",
        "## F. Current safety model",
        "## G. Claude review checklist",
    ],
    "docs/PHASE_2_HARDENING_REPORT.md": [
        "## Known limitations fixed",
        "## Known limitations remaining",
        "## Test coverage summary",
        "## Validator summary",
        "## Risk register",
        "## Recommended fixes before Phase 3",
        "## Phase 2 readiness for Claude review",
    ],
    "docs/PHASE_3_READINESS_CRITERIA.md": [
        "## A. Execution gates",
        "## B. Approval gates",
        "## C. Sandbox gates",
        "## D. Logging gates",
        "## E. Rollback gates",
    ],
}

PHASE_2_HARDENING_ADRS = (
    "decisions/ADR-0010-phase-2-runtime-registries.md",
    "decisions/ADR-0011-langgraph-planning-only-orchestrator.md",
    "decisions/ADR-0012-phase-3-agent-dispatch-gates.md",
)


def validate_phase2_review_docs(errors: list[str]) -> None:
    for rel, sections in PHASE_2_REVIEW_REQUIRED_FILES.items():
        path = ROOT / rel
        if not path.exists():
            errors.append(f"{rel}: file does not exist (Phase 2.5 review packet)")
            continue
        text = path.read_text(encoding="utf-8")
        for section in sections:
            if section not in text:
                errors.append(f"{rel}: missing required section {section}")


def validate_phase2_hardening_adrs(errors: list[str]) -> None:
    for rel in PHASE_2_HARDENING_ADRS:
        path = ROOT / rel
        if not path.exists():
            errors.append(f"{rel}: file does not exist (Phase 2.5 ADR)")
            continue
        text = path.read_text(encoding="utf-8")
        for section in REQUIRED_ADR_SECTIONS:
            if section not in text:
                errors.append(f"{rel}: missing required section {section}")


def validate_obsidian_mapping(errors: list[str]) -> None:
    path = ROOT / "memory" / "obsidian_mapping.yaml"
    rel = path.relative_to(ROOT)
    if not path.exists():
        errors.append(f"{rel}: file does not exist")
        return
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{rel}: invalid YAML: {exc}")
        return
    if not isinstance(data, dict):
        errors.append(f"{rel}: root must be a YAML mapping")
        return
    missing = sorted(OBSIDIAN_MAPPING_REQUIRED_FIELDS - set(data))
    if missing:
        errors.append(f"{rel}: missing required fields: {', '.join(missing)}")
    if not isinstance(data.get("output_folders"), dict):
        errors.append(f"{rel}: output_folders must be a mapping")
    if not isinstance(data.get("include_sections"), list):
        errors.append(f"{rel}: include_sections must be a list")
    if not isinstance(data.get("exclude_patterns"), list):
        errors.append(f"{rel}: exclude_patterns must be a list")
    if not isinstance(data.get("sync_enabled"), bool):
        errors.append(f"{rel}: sync_enabled must be a boolean")
    if not isinstance(data.get("dry_run_default"), bool):
        errors.append(f"{rel}: dry_run_default must be a boolean")
    root_folder = data.get("vault_root_folder")
    if isinstance(root_folder, str) and ".." in Path(root_folder).parts:
        errors.append(f"{rel}: vault_root_folder must not contain '..' segments")
    output_folders = data.get("output_folders", {})
    if isinstance(output_folders, dict):
        for key, value in output_folders.items():
            if isinstance(value, str) and ".." in Path(value).parts:
                errors.append(f"{rel}: output_folders.{key} must not contain '..' segments")


ADAPTER_REQUIRED_FIELDS = {
    "id",
    "display_name",
    "agent_id",
    "adapter_type",
    "status",
    "command_template",
    "allowed_commands",
    "forbidden_args",
    "required_clis",
    "env_vars_required",
    "secrets_required",
    "timeout_seconds",
    "working_directory_policy",
    "supports_dry_run",
    "supports_streaming",
    "supports_execution",
    "writes_files",
    "approval_level",
    "risk_level",
    "notes",
}
ALLOWED_ADAPTER_TYPES = {"cli", "mcp", "http"}
ALLOWED_ADAPTER_STATUSES = {"active", "disabled", "planned"}
ALLOWED_WD_POLICIES = {"repo_root", "worktree", "task_subdir"}
ADAPTER_LIST_FIELDS = {"allowed_commands", "forbidden_args", "required_clis", "env_vars_required"}


def validate_adapter_registry(errors: list[str]) -> None:
    path = ROOT / "agents" / "adapter_registry.yaml"
    rel = path.relative_to(ROOT)
    if not path.exists():
        errors.append(f"{rel}: file does not exist")
        return
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{rel}: invalid YAML: {exc}")
        return
    if not isinstance(data, dict):
        errors.append(f"{rel}: root must be a YAML mapping")
        return
    adapters = data.get("adapters")
    if not isinstance(adapters, list):
        errors.append(f"{rel}: adapters must be a list")
        return
    if not adapters:
        errors.append(f"{rel}: adapters must contain at least one entry")
        return

    seen_ids: set[str] = set()
    active_count = 0
    for index, adapter in enumerate(adapters, start=1):
        prefix = f"{rel}:adapters[{index}]"
        if not isinstance(adapter, dict):
            errors.append(f"{prefix}: adapter entry must be a mapping")
            continue
        adapter_id = adapter.get("id")
        if not isinstance(adapter_id, str) or not adapter_id.strip():
            errors.append(f"{prefix}: id must be a non-empty string")
        elif adapter_id in seen_ids:
            errors.append(f"{prefix}: duplicate adapter id {adapter_id!r}")
        else:
            seen_ids.add(adapter_id)

        missing = sorted(ADAPTER_REQUIRED_FIELDS - set(adapter))
        if missing:
            errors.append(f"{prefix} ({adapter_id or 'unknown'}): missing required fields: {', '.join(missing)}")

        if adapter.get("adapter_type") not in ALLOWED_ADAPTER_TYPES:
            errors.append(f"{prefix} ({adapter_id}): invalid adapter_type {adapter.get('adapter_type')!r}")

        if adapter.get("status") not in ALLOWED_ADAPTER_STATUSES:
            errors.append(f"{prefix} ({adapter_id}): invalid status {adapter.get('status')!r}")

        if adapter.get("status") == "active":
            active_count += 1
            if not adapter.get("supports_dry_run"):
                errors.append(f"{prefix} ({adapter_id}): active adapters must have supports_dry_run: true in Phase 3.0")

        if adapter.get("working_directory_policy") not in ALLOWED_WD_POLICIES:
            errors.append(
                f"{prefix} ({adapter_id}): invalid working_directory_policy "
                f"{adapter.get('working_directory_policy')!r}"
            )

        if not isinstance(adapter.get("secrets_required"), bool):
            errors.append(f"{prefix} ({adapter_id}): secrets_required must be a boolean")

        supports_execution = adapter.get("supports_execution")
        if supports_execution is None:
            errors.append(f"{prefix} ({adapter_id}): missing required field supports_execution")
        elif not isinstance(supports_execution, bool):
            errors.append(f"{prefix} ({adapter_id}): supports_execution must be a boolean")

        risk_level = adapter.get("risk_level")
        if risk_level not in ALLOWED_RISK_LEVELS:
            errors.append(f"{prefix} ({adapter_id}): invalid risk_level {risk_level!r}")

        approval_level = adapter.get("approval_level")
        if approval_level not in ALLOWED_SKILL_APPROVAL_LEVELS:
            errors.append(f"{prefix} ({adapter_id}): invalid approval_level {approval_level!r}")

        for list_field in ADAPTER_LIST_FIELDS:
            if list_field in adapter and not isinstance(adapter[list_field], list):
                errors.append(f"{prefix} ({adapter_id}): {list_field} must be a list")

    if active_count == 0:
        errors.append(f"{rel}: at least one active adapter is required for Phase 3.0 preview")

    validate_phase35_adapter_boundaries(errors, adapters)
    validate_phase36_codex_activation_readiness(errors)
    validate_phase37a_codex_canary_activation(errors)
    validate_phase37a1_executor_bypass(errors)
    validate_phase37c_local_builder(errors)
    validate_phase38_composer_integration(errors)


PROMOTION_EXECUTION_STATES = {
    "restricted_candidate": False,
    "preview_only": False,
    "planned": False,
    "test_execution": False,
    "disabled": False,
    "revoked": False,
    "activation_candidate": True,
    "restricted_execution": True,
    "active": True,
}


def _phase37a_active() -> bool:
    return (ROOT / "dispatch" / "codex_activation_gate.py").is_file()


def _phase37c_active() -> bool:
    return (
        (ROOT / "config" / "execution-policy.yaml").is_file()
        and (ROOT / "dispatch" / "codex_local_builder.py").is_file()
    )


def validate_phase35_adapter_boundaries(errors: list[str], adapters: list[Any]) -> None:
    """Phase 3.5: codex-restricted candidate + single executable adapter invariant."""
    execution_capable: list[str] = []
    codex_restricted: dict[str, Any] | None = None

    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        adapter_id = str(adapter.get("id", ""))
        if adapter.get("supports_execution"):
            execution_capable.append(adapter_id)

        promotion_state = adapter.get("promotion_state")
        if promotion_state is not None:
            expected = PROMOTION_EXECUTION_STATES.get(str(promotion_state))
            if expected is None:
                errors.append(
                    f"agents/adapter_registry.yaml ({adapter_id}): unknown promotion_state {promotion_state!r}"
                )
            elif bool(adapter.get("supports_execution")) != expected:
                errors.append(
                    f"agents/adapter_registry.yaml ({adapter_id}): promotion_state {promotion_state!r} "
                    f"contradicts supports_execution={adapter.get('supports_execution')}"
                )

        if adapter_id == "codex-restricted":
            codex_restricted = adapter

    phase37a = _phase37a_active()
    phase37c = _phase37c_active()
    allowed_execution = (
        ["local-python-exec-test", "codex-restricted"] if phase37a else ["local-python-exec-test"]
    )
    if sorted(execution_capable) != sorted(allowed_execution):
        errors.append(
            "agents/adapter_registry.yaml: execution-capable adapters must be "
            f"{allowed_execution!r}; found {execution_capable!r}"
        )

    if codex_restricted is None:
        errors.append("agents/adapter_registry.yaml: missing codex-restricted adapter entry")
        return

    if phase37c:
        if not codex_restricted.get("supports_execution"):
            errors.append("codex-restricted must have supports_execution=true in Phase 3.7C")
        if codex_restricted.get("execution_scope") != "local_worktree":
            errors.append("codex-restricted execution_scope must be local_worktree in Phase 3.7C")
        if codex_restricted.get("required_execution_route") != "codex_local_builder":
            errors.append("codex-restricted required_execution_route must be codex_local_builder")
        if codex_restricted.get("phase3_7b_authorization_required"):
            errors.append("codex-restricted must not require phase3_7b authorization in Phase 3.7C")
    elif phase37a:
        if not codex_restricted.get("supports_execution"):
            errors.append("codex-restricted must have supports_execution=true in Phase 3.7A")
        if codex_restricted.get("promotion_state") != "activation_candidate":
            errors.append("codex-restricted promotion_state must be activation_candidate in Phase 3.7A")
        if codex_restricted.get("execution_scope") != "canary_only":
            errors.append("codex-restricted execution_scope must be canary_only in Phase 3.7A")
        if int(codex_restricted.get("maximum_runs", 0) or 0) != 1:
            errors.append("codex-restricted maximum_runs must equal 1 in Phase 3.7A")
    else:
        if codex_restricted.get("supports_execution"):
            errors.append("codex-restricted must have supports_execution=false in Phase 3.5")
        if codex_restricted.get("promotion_state") != "restricted_candidate":
            errors.append("codex-restricted promotion_state must be restricted_candidate")
    if phase37c:
        if codex_restricted.get("approval_level") not in {"none", "standing_policy"}:
            errors.append("codex-restricted approval_level must be none in Phase 3.7C")
    elif codex_restricted.get("approval_level") != "human":
        errors.append("codex-restricted approval_level must be human")
    if not codex_restricted.get("worktree_required"):
        errors.append("codex-restricted worktree_required must be true")
    if not codex_restricted.get("network_required"):
        errors.append("codex-restricted network_required must be true")
    if not codex_restricted.get("secrets_required"):
        errors.append("codex-restricted secrets_required must be true")

    dedicated_path = ROOT / "agents" / "codex_restricted_adapter.yaml"
    if not dedicated_path.exists():
        errors.append("agents/codex_restricted_adapter.yaml: file does not exist")
        return
    try:
        dedicated = yaml.safe_load(dedicated_path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"agents/codex_restricted_adapter.yaml: invalid YAML: {exc}")
        return
    if not isinstance(dedicated, dict):
        errors.append("agents/codex_restricted_adapter.yaml: root must be a mapping")
        return
    if phase37c:
        if not dedicated.get("supports_execution"):
            errors.append("agents/codex_restricted_adapter.yaml: supports_execution must be true in Phase 3.7C")
        if dedicated.get("execution_scope") != "local_worktree":
            errors.append("agents/codex_restricted_adapter.yaml: execution_scope must be local_worktree")
        if dedicated.get("required_execution_route") != "codex_local_builder":
            errors.append("agents/codex_restricted_adapter.yaml: required_execution_route must be codex_local_builder")
        if dedicated.get("phase3_7b_authorization_required"):
            errors.append("agents/codex_restricted_adapter.yaml: phase3_7b_authorization_required must be false")
    elif phase37a:
        if not dedicated.get("supports_execution"):
            errors.append("agents/codex_restricted_adapter.yaml: supports_execution must be true in Phase 3.7A")
        if dedicated.get("promotion_state") != "activation_candidate":
            errors.append("agents/codex_restricted_adapter.yaml: promotion_state must be activation_candidate")
        if dedicated.get("execution_scope") != "canary_only":
            errors.append("agents/codex_restricted_adapter.yaml: execution_scope must be canary_only")
        if dedicated.get("live_run_authorized"):
            errors.append("agents/codex_restricted_adapter.yaml: live_run_authorized must be false")
        if not dedicated.get("phase3_7b_authorization_required"):
            errors.append("agents/codex_restricted_adapter.yaml: phase3_7b_authorization_required must be true")
    else:
        if dedicated.get("supports_execution"):
            errors.append("agents/codex_restricted_adapter.yaml: supports_execution must be false")
    if dedicated.get("id") != "codex-restricted":
        errors.append("agents/codex_restricted_adapter.yaml: id must be codex-restricted")


def validate_phase36_codex_activation_readiness(errors: list[str]) -> None:
    """Phase 3.6: MA1 command contract, activation package, canary refusal boundary."""
    if not (ROOT / "dispatch" / "codex_activation.py").is_file():
        return
    from dispatch.codex_adapter import (
        append_codex_prompt,
        build_codex_exec_options,
        compute_command_contract_hash,
        load_codex_restricted_adapter,
        validate_codex_argv_contract,
        CODEX_EXECUTABLE,
    )
    from dispatch.codex_canary_contract import compute_canary_contract_hash

    required_docs = (
        "docs/PHASE_3_6_CODEX_ACTIVATION_READINESS.md",
        "docs/PHASE_3_6_CODEX_COMMAND_CONTRACT.md",
        "docs/PHASE_3_6_CODEX_CANARY_RUNBOOK.md",
        "docs/PHASE_3_6_CODEX_ROLLBACK.md",
        "docs/PHASE_3_6_HUMAN_APPROVAL_CHECKLIST.md",
    )
    for rel in required_docs:
        if not (ROOT / rel).exists():
            errors.append(f"Phase 3.6: missing document {rel}")

    for rel in (
        "schemas/codex_activation_manifest.schema.json",
        "schemas/codex_canary_record.schema.json",
        "dispatch/codex_activation.py",
        "dispatch/codex_canary_contract.py",
        "dispatch/codex_cli_compatibility.py",
        "dispatch/codex_canary_gates.py",
        "scripts/validate_codex_activation.py",
        "scripts/prepare_codex_canary.py",
    ):
        if not (ROOT / rel).exists():
            errors.append(f"Phase 3.6: missing artifact {rel}")

    try:
        adapter = load_codex_restricted_adapter(ROOT)
    except (OSError, ValueError) as exc:
        errors.append(f"Phase 3.6: codex adapter config unavailable: {exc}")
        return

    if not _phase37a_active() and adapter.get("supports_execution"):
        errors.append("Phase 3.6: codex-restricted supports_execution must remain false")

    sample_argv = append_codex_prompt(
        [
            CODEX_EXECUTABLE,
            *build_codex_exec_options(adapter, worktree_path="/wt", agent_output_path="/out/msg.txt"),
        ],
        "contract validation prompt",
    )
    contract_blocked = validate_codex_argv_contract(
        sample_argv,
        agent_output_path="/out/msg.txt",
        prompt="contract validation prompt",
    )
    if contract_blocked:
        errors.append(f"Phase 3.6: codex argv contract failed: {contract_blocked}")

    if not compute_command_contract_hash() or not compute_canary_contract_hash():
        errors.append("Phase 3.6: contract hashes must be non-empty")

    canary_script = ROOT / "scripts" / "run_codex_canary.py"
    if canary_script.is_file():
        canary_source = canary_script.read_text(encoding="utf-8")
        if "codex_subprocess_invoked" not in canary_source:
            errors.append("Phase 3.6: run_codex_canary.py must refuse before Codex subprocess")
        if "return 3" not in canary_source:
            errors.append("Phase 3.6: run_codex_canary.py must exit refused")
        if _phase37a_active() and "phase3_7b" not in canary_source.lower():
            errors.append("Phase 3.7A: run_codex_canary.py must require Phase 3.7B authorization")


def validate_phase37a_codex_canary_activation(errors: list[str]) -> None:
    """Phase 3.7A: activation candidate package, live-run prohibition, gate module."""
    if not _phase37a_active():
        return

    required_docs = (
        "docs/PHASE_3_7A_BASELINE.md",
        "docs/PHASE_3_7A_CODEX_ACTIVATION_CANDIDATE.md",
        "docs/PHASE_3_7A_CANARY_PREFLIGHT.md",
        "docs/PHASE_3_7A_HUMAN_APPROVAL_REQUEST.md",
        "docs/PHASE_3_7A_LIVE_RUN_PROHIBITION.md",
        "docs/PHASE_3_7A_HARDENING_REPORT.md",
        "docs/PHASE_3_7A_REVIEW_PACKET.md",
    )
    for rel in required_docs:
        if not (ROOT / rel).exists():
            errors.append(f"Phase 3.7A: missing document {rel}")

    required_artifacts = (
        "dispatch/codex_activation_gate.py",
        "scripts/disable_codex_canary.py",
        "scripts/verify_codex_canary_package.py",
        "schemas/codex_human_approval_request.schema.json",
        "tasks/active/T-PHASE3-7A-CODEX-CANARY-ACTIVATION.yaml",
    )
    for rel in required_artifacts:
        if not (ROOT / rel).exists():
            errors.append(f"Phase 3.7A: missing artifact {rel}")

    required_tests = (
        "tests/test_phase3_7a_activation_state.py",
        "tests/test_phase3_7a_cli_preflight.py",
        "tests/test_phase3_7a_activation_manifest.py",
        "tests/test_phase3_7a_canary_package.py",
        "tests/test_phase3_7a_human_gate.py",
        "tests/test_phase3_7a_no_live_execution.py",
        "tests/test_phase3_7a_safety_boundaries.py",
    )
    for rel in required_tests:
        if not (ROOT / rel).exists():
            errors.append(f"Phase 3.7A: missing test {rel}")

    for rel in (
        "decisions/ADR-0038-codex-canary-only-activation-state.md",
        "decisions/ADR-0039-preflight-live-run-prohibited-boundary.md",
        "decisions/ADR-0040-human-authorization-one-shot-canary.md",
        "decisions/ADR-0041-automatic-post-canary-suspension.md",
    ):
        if not (ROOT / rel).exists():
            errors.append(f"Phase 3.7A: missing ADR {rel}")

    runner_source = (ROOT / "scripts" / "run_codex_canary.py").read_text(encoding="utf-8")
    if "subprocess" in runner_source and "subprocess.run" in runner_source:
        errors.append("Phase 3.7A: run_codex_canary.py must not invoke subprocess.run")

    gate_source = (ROOT / "dispatch" / "codex_activation_gate.py").read_text(encoding="utf-8")
    if "PHASE3_7B_BLOCKED_REASON" not in gate_source:
        errors.append("Phase 3.7A: codex_activation_gate.py must define Phase 3.7B blocked reason")


def validate_phase37a1_executor_bypass(errors: list[str]) -> None:
    """Phase 3.7A.1: generic executor must reject canary-only adapters (H1)."""
    policy_path = ROOT / "dispatch" / "execution_route_policy.py"
    if not policy_path.is_file():
        errors.append("Phase 3.7A.1: missing dispatch/execution_route_policy.py")
        return

    test_path = ROOT / "tests" / "test_phase3_7a_1_executor_bypass.py"
    if not test_path.is_file():
        errors.append("Phase 3.7A.1: missing tests/test_phase3_7a_1_executor_bypass.py")

    from dispatch.execution_route_policy import (
        DEDICATED_CANARY_RUNNER_REASON,
        RECOGNIZED_EXECUTION_ROUTES,
        ROUTE_CODEX_CANARY,
        ROUTE_GENERIC_DISPATCH,
        evaluate_execution_route,
        validate_adapter_route_policy,
    )

    if DEDICATED_CANARY_RUNNER_REASON not in policy_path.read_text(encoding="utf-8"):
        errors.append("Phase 3.7A.1: dedicated runner blocked reason missing from policy module")

    gate_source = (ROOT / "dispatch" / "execution_gate.py").read_text(encoding="utf-8")
    if "evaluate_execution_route" not in gate_source:
        errors.append("Phase 3.7A.1: execution_gate.py must call evaluate_execution_route")

    executor_source = (ROOT / "dispatch" / "executor.py").read_text(encoding="utf-8")
    if "ROUTE_GENERIC_DISPATCH" not in executor_source:
        errors.append("Phase 3.7A.1: executor.py must use generic_dispatch route")

    try:
        registry = yaml.safe_load((ROOT / "agents" / "adapter_registry.yaml").read_text(encoding="utf-8"))
        codex = next(a for a in registry["adapters"] if a["id"] == "codex-restricted")
    except Exception as exc:
        errors.append(f"Phase 3.7A.1: cannot load codex-restricted adapter: {exc}")
        return

    if not codex.get("dedicated_runner_required"):
        errors.append("Phase 3.7A.1: codex-restricted must declare dedicated_runner_required=true")
    from dispatch.execution_route_policy import ROUTE_CODEX_LOCAL_BUILDER

    expected_route = ROUTE_CODEX_LOCAL_BUILDER if _phase37c_active() else ROUTE_CODEX_CANARY
    if codex.get("required_execution_route") != expected_route:
        errors.append(f"Phase 3.7A.1: codex-restricted required_execution_route must be {expected_route}")
    errors.extend(validate_adapter_route_policy(codex))

    generic_block = evaluate_execution_route(codex, ROUTE_GENERIC_DISPATCH)
    if generic_block.allowed:
        errors.append("Phase 3.7A.1: generic_dispatch must block codex-restricted")
    if DEDICATED_CANARY_RUNNER_REASON not in generic_block.reasons:
        errors.append("Phase 3.7A.1: generic_dispatch block must cite dedicated canary runner reason")

    if _phase37c_active():
        builder_allow = evaluate_execution_route(codex, ROUTE_CODEX_LOCAL_BUILDER)
        if not builder_allow.allowed:
            errors.append(
                f"Phase 3.7C: codex_local_builder route must be allowed: {builder_allow.reasons}"
            )
    else:
        canary_allow = evaluate_execution_route(codex, ROUTE_CODEX_CANARY)
        if not canary_allow.allowed:
            errors.append(f"Phase 3.7A.1: codex_canary route must be allowed at policy layer: {canary_allow.reasons}")

    capable = [a["id"] for a in registry["adapters"] if a.get("supports_execution")]
    if sorted(capable) != ["codex-restricted", "local-python-exec-test"]:
        errors.append(f"Phase 3.7A.1: unexpected execution-capable adapters: {capable!r}")

    for adapter in registry["adapters"]:
        if adapter.get("id") == "local-python-exec-test":
            errors.extend(validate_adapter_route_policy(adapter))
            local_route = evaluate_execution_route(adapter, ROUTE_GENERIC_DISPATCH)
            if not local_route.allowed:
                errors.append("Phase 3.7A.1: local-python-exec-test must remain generic-dispatch compatible")

    if str(codex.get("required_execution_route", "")) not in RECOGNIZED_EXECUTION_ROUTES:
        errors.append("Phase 3.7A.1: codex required_execution_route not recognized")


def validate_phase37c_local_builder(errors: list[str]) -> None:
    """Phase 3.7C: autonomous local builder — standing policy, dedicated runner."""
    if not _phase37c_active():
        return

    required_docs = (
        "docs/AUTONOMOUS_LOCAL_BUILDER.md",
        "docs/CODEX_LOCAL_BUILDER_RUNBOOK.md",
    )
    for rel in required_docs:
        if not (ROOT / rel).exists():
            errors.append(f"Phase 3.7C: missing document {rel}")

    required_artifacts = (
        "config/execution-policy.yaml",
        "dispatch/execution_policy.py",
        "dispatch/codex_local_builder.py",
        "dispatch/codex_local_builder_gate.py",
        "dispatch/local_builder_runs.py",
        "scripts/run_codex_builder.py",
        "scripts/run_local_builder_worker.py",
        "tasks/active/T-FIRST-AUTONOMOUS-CODEX-BUILD.yaml",
        "tests/test_phase3_7c_local_builder.py",
    )
    for rel in required_artifacts:
        if not (ROOT / rel).exists():
            errors.append(f"Phase 3.7C: missing artifact {rel}")

    from dispatch.execution_policy import load_execution_policy, validate_execution_policy
    from dispatch.execution_route_policy import ROUTE_CODEX_LOCAL_BUILDER, evaluate_execution_route
    from dispatch.codex_adapter import load_codex_restricted_adapter

    try:
        policy = load_execution_policy(ROOT)
    except (OSError, ValueError) as exc:
        errors.append(f"Phase 3.7C: execution policy invalid: {exc}")
        return
    errors.extend(validate_execution_policy(policy))

    try:
        adapter = load_codex_restricted_adapter(ROOT)
    except (OSError, ValueError) as exc:
        errors.append(f"Phase 3.7C: codex adapter unavailable: {exc}")
        return

    builder_route = evaluate_execution_route(adapter, ROUTE_CODEX_LOCAL_BUILDER)
    if not builder_route.allowed:
        errors.append(f"Phase 3.7C: codex_local_builder route blocked: {builder_route.reasons}")

    builder_source = (ROOT / "scripts" / "run_codex_builder.py").read_text(encoding="utf-8")
    if "approval_signing" in builder_source or "try_claim_approval" in builder_source:
        errors.append("Phase 3.7C: run_codex_builder.py must not use approval signing or replay")
    core_path = ROOT / "dispatch" / "local_builder_core.py"
    builder_path = ROOT / "dispatch" / "codex_local_builder.py"
    subprocess_ok = (
        core_path.is_file() and "subprocess.run" in core_path.read_text(encoding="utf-8")
    ) or "subprocess.run" in builder_path.read_text(encoding="utf-8")
    if not subprocess_ok:
        errors.append("Phase 3.7C: local builder core must invoke subprocess.run for agent CLI")


def validate_phase38_composer_integration(errors: list[str]) -> None:
    """Phase 3.8: Composer preview scaffolding — route, adapter, assignment channel."""
    required = (
        "decisions/ADR-0043-composer-grok-build-integration.md",
        "agents/composer_restricted_adapter.yaml",
        "dispatch/composer_adapter.py",
        "dispatch/assignment_channel.py",
        "dispatch/local_builder_core.py",
        "docs/COMPOSER_LOCAL_BUILDER_PREVIEW.md",
        "tests/test_phase3_8_composer_integration.py",
        "tests/test_assignment_channel.py",
    )
    for rel in required:
        if not (ROOT / rel).exists():
            errors.append(f"Phase 3.8: missing artifact {rel}")

    from dispatch.composer_adapter import (
        load_composer_restricted_adapter,
        validate_composer_preview_contract,
    )
    from dispatch.execution_route_policy import (
        ROUTE_COMPOSER_LOCAL_BUILDER,
        evaluate_execution_route,
        validate_adapter_route_policy,
    )

    try:
        composer = load_composer_restricted_adapter(ROOT)
    except (OSError, ValueError) as exc:
        errors.append(f"Phase 3.8: composer adapter unavailable: {exc}")
        return

    errors.extend(validate_composer_preview_contract(composer))
    errors.extend(validate_adapter_route_policy(composer))
    route = evaluate_execution_route(composer, ROUTE_COMPOSER_LOCAL_BUILDER)
    if not route.allowed:
        errors.append(f"Phase 3.8: composer_local_builder route blocked: {route.reasons}")

    try:
        registry = yaml.safe_load((ROOT / "agents" / "adapter_registry.yaml").read_text(encoding="utf-8"))
        entry = next(a for a in registry["adapters"] if a["id"] == "composer-restricted")
    except Exception as exc:
        errors.append(f"Phase 3.8: composer-restricted registry entry missing: {exc}")
        return

    if entry.get("supports_execution"):
        errors.append("Phase 3.8: composer-restricted registry supports_execution must be false")
    errors.extend(validate_adapter_route_policy(entry))

    policy_path = ROOT / "config" / "execution-policy.yaml"
    if policy_path.is_file():
        policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        enabled = policy.get("enabled_adapters") or []
        if "composer-restricted" in enabled:
            errors.append("Phase 3.8: composer-restricted must not be in enabled_adapters yet")

    policy_source = (ROOT / "dispatch" / "execution_route_policy.py").read_text(encoding="utf-8")
    if "ROUTE_COMPOSER_LOCAL_BUILDER" not in policy_source:
        errors.append("Phase 3.8: ROUTE_COMPOSER_LOCAL_BUILDER missing from execution_route_policy.py")


def validate_skill_mcp_references(errors: list[str]) -> None:
    skills_path = ROOT / "skills" / "registry.yaml"
    mcps_path = ROOT / "mcps" / "registry.yaml"
    if not skills_path.exists() or not mcps_path.exists():
        return
    try:
        skills_data = yaml.safe_load(skills_path.read_text(encoding="utf-8"))
        mcps_data = yaml.safe_load(mcps_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(skills_data, dict) or not isinstance(mcps_data, dict):
        return
    mcp_ids = {
        m.get("id")
        for m in mcps_data.get("mcps", [])
        if isinstance(m, dict) and isinstance(m.get("id"), str)
    }
    for index, skill in enumerate(skills_data.get("skills", []), start=1):
        if not isinstance(skill, dict):
            continue
        skill_id = skill.get("id", "unknown")
        for ref in skill.get("required_mcps", []):
            if isinstance(ref, str) and ref not in mcp_ids:
                errors.append(
                    f"skills/registry.yaml:skills[{index}] ({skill_id}): "
                    f"required_mcps references unknown MCP id {ref!r}"
                )


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    validate_tasks(errors, warnings)
    validate_logs(errors, warnings)
    validate_handoffs(errors)
    validate_adrs(errors)
    validate_skills_registry(errors)
    validate_mcps_registry(errors)
    validate_skill_mcp_references(errors)
    skill_ids = _load_registry_ids(ROOT / "skills" / "registry.yaml", "skills")
    mcp_ids = _load_registry_ids(ROOT / "mcps" / "registry.yaml", "mcps")
    role_ids = validate_roles_registry(errors, skill_ids, mcp_ids)
    validate_teams_registry(errors, skill_ids, mcp_ids, role_ids)
    validate_obsidian_mapping(errors)
    validate_adapter_registry(errors)
    validate_phase2_review_docs(errors)
    validate_phase2_hardening_adrs(errors)

    for warning in warnings:
        print(f"Warning: {warning}", file=sys.stderr)

    if errors:
        print("Validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
