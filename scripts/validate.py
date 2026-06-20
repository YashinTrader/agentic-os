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

HANDOFF_PROTOCOL_V2_MARKER = "**Handoff Protocol:** v2"

REQUIRED_VERIFICATION_FIELDS = (
    "repo_root:",
    "branch:",
    "base_sha:",
    "local_head_sha:",
    "remote_head_sha:",
    "git_status_clean:",
    "tests_commit_sha:",
    "test_count:",
    "test_exit_code:",
    "validator_exit_code:",
    "validator_commit_sha:",
    "artifact_commit_sha:",
    "working_copy_path:",
)

_SHA40_RE = re.compile(r"^[0-9a-fA-F]{40}$")

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


def _verification_field_value(text: str, field: str) -> str | None:
    prefix = field if field.endswith(":") else f"{field}:"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return None


def validate_handoff_verification_block(rel: str, text: str, errors: list[str]) -> None:
    """Require Repository Verification block for Handoff Protocol v2 handoffs only."""
    if HANDOFF_PROTOCOL_V2_MARKER not in text:
        return
    if "## Repository Verification" not in text:
        errors.append(f"{rel}: v2 handoff missing section ## Repository Verification")
        return
    for field in REQUIRED_VERIFICATION_FIELDS:
        if field not in text:
            errors.append(f"{rel}: v2 handoff missing verification field {field}")
    for sha_field in ("base_sha:", "local_head_sha:", "remote_head_sha:", "tests_commit_sha:", "validator_commit_sha:", "artifact_commit_sha:"):
        value = _verification_field_value(text, sha_field)
        if value is None:
            continue
        if not _SHA40_RE.match(value):
            errors.append(f"{rel}: {sha_field} must be a 40-character hex SHA ({value!r})")
    test_exit = _verification_field_value(text, "test_exit_code:")
    if test_exit is not None and test_exit != "0":
        errors.append(f"{rel}: test_exit_code must be 0 for v2 handoff (got {test_exit!r})")
    validator_exit = _verification_field_value(text, "validator_exit_code:")
    if validator_exit is not None and validator_exit != "0":
        errors.append(f"{rel}: validator_exit_code must be 0 for v2 handoff (got {validator_exit!r})")
    local_head = _verification_field_value(text, "local_head_sha:")
    remote_head = _verification_field_value(text, "remote_head_sha:")
    if local_head and remote_head and local_head.lower() != remote_head.lower():
        errors.append(
            f"{rel}: local_head_sha ({local_head}) does not match remote_head_sha ({remote_head})"
        )


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
