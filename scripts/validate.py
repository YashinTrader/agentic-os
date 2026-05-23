#!/usr/bin/env python3
"""Validate the Agentic OS file coordination skeleton."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only without dependency.
    print("PyYAML is required. Install with: python -m pip install -r requirements.txt", file=sys.stderr)
    sys.exit(2)


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

ALLOWED_EVENT_TYPES = {
    "task_created",
    "task_assigned",
    "status_changed",
    "handoff_written",
    "reviewed",
    "decision_recorded",
    "blocked",
    "note",
}
V1_ALLOWED_EVENTS = {"started", "progress", "blocked", "decision_needed", "handoff", "finished", "error"}

REQUIRED_HANDOFF_SECTIONS = [
    "## What I Did",
    "## What Remains",
    "## Decisions Made",
    "## Open Questions",
    "## How to Verify My Work",
    "## Risks / Caveats",
    "## Recommended Next Action for Receiver",
]

REQUIRED_ADR_SECTIONS = [
    "## Context",
    "## Decision",
    "## Consequences",
]


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
                warnings.append(f"logs/agent-events.jsonl:{index}: unknown event type {event['type']!r}")
        elif "event" in event:
            warnings.append(f"logs/agent-events.jsonl:{index}: uses deprecated v1 field 'event'; use 'type'")
            if event["event"] not in V1_ALLOWED_EVENTS:
                warnings.append(f"logs/agent-events.jsonl:{index}: unknown v1 event {event['event']!r}")
        else:
            errors.append("logs/agent-events.jsonl:{index}: missing required field 'type'")


def validate_handoffs(errors: list[str]) -> None:
    for path in sorted((ROOT / "handoffs").glob("*.md")):
        if path.name == "README.md":
            continue
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        if not text.startswith("# Handoff: "):
            errors.append(f"{rel}: must start with '# Handoff: <task-id>'")
        for marker in ("**From:**", "**To:**", "**Date:**", "**Task Status After Handoff:**"):
            if marker not in text:
                errors.append(f"{rel}: missing metadata marker {marker}")
        for section in REQUIRED_HANDOFF_SECTIONS:
            if section not in text:
                errors.append(f"{rel}: missing required section {section}")


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


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    validate_tasks(errors, warnings)
    validate_logs(errors, warnings)
    validate_handoffs(errors)
    validate_adrs(errors)

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
