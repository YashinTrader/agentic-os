#!/usr/bin/env python3
"""Validate the Agentic OS Phase 1 file coordination skeleton."""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only without dependency.
    print("PyYAML is required. Install with: python -m pip install -r requirements.txt", file=sys.stderr)
    sys.exit(2)


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_TASK_FIELDS = {
    "id",
    "title",
    "owner",
    "status",
    "created",
    "updated",
    "objective",
    "inputs",
    "outputs",
    "constraints",
    "acceptance_criteria",
    "handoff_notes",
    "risk_level",
    "requires_human_approval",
}

ALLOWED_STATUSES = {"todo", "in_progress", "review", "blocked", "done"}
ALLOWED_RISK_LEVELS = {"low", "medium", "high"}
REQUIRED_LOG_FIELDS = {"ts", "agent", "task", "event"}

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
    "## Alternatives Considered",
    "## Consequences",
    "## References",
]

REQUIRED_ADR_METADATA = [
    "**Status:**",
    "**Date:**",
    "**Author (agent):**",
    "**Reviewer (agent):**",
    "**Approval:**",
]


def task_files() -> list[Path]:
    paths: list[Path] = []
    for directory in ("tasks/active", "tasks/done", "tasks/blocked"):
        paths.extend(sorted((ROOT / directory).glob("*.yaml")))
        paths.extend(sorted((ROOT / directory).glob("*.yml")))
    return paths


def validate_tasks(errors: list[str]) -> None:
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

        missing = sorted(REQUIRED_TASK_FIELDS - set(data))
        if missing:
            errors.append(f"{rel}: missing required fields: {', '.join(missing)}")

        status = data.get("status")
        if status not in ALLOWED_STATUSES:
            errors.append(f"{rel}: invalid status {status!r}; expected one of {sorted(ALLOWED_STATUSES)}")

        risk_level = data.get("risk_level")
        if risk_level not in ALLOWED_RISK_LEVELS:
            errors.append(f"{rel}: invalid risk_level {risk_level!r}; expected one of {sorted(ALLOWED_RISK_LEVELS)}")

        if not isinstance(data.get("requires_human_approval"), bool):
            errors.append(f"{rel}: requires_human_approval must be a boolean")

        for list_field in ("inputs", "outputs", "constraints", "acceptance_criteria"):
            if list_field in data and not isinstance(data[list_field], list):
                errors.append(f"{rel}: {list_field} must be a list")


def validate_logs(errors: list[str]) -> None:
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
        missing = sorted(REQUIRED_LOG_FIELDS - set(event))
        if missing:
            errors.append(f"logs/agent-events.jsonl:{index}: missing required fields: {', '.join(missing)}")


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


def validate_adrs(errors: list[str]) -> None:
    for path in sorted((ROOT / "decisions").glob("ADR-*.md")):
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        if not text.startswith("# ADR-"):
            errors.append(f"{rel}: must start with '# ADR-####: <title>'")
        for marker in REQUIRED_ADR_METADATA:
            if marker not in text:
                errors.append(f"{rel}: missing metadata marker {marker}")
        for section in REQUIRED_ADR_SECTIONS:
            if section not in text:
                errors.append(f"{rel}: missing required section {section}")


def main() -> int:
    errors: list[str] = []
    validate_tasks(errors)
    validate_logs(errors)
    validate_handoffs(errors)
    validate_adrs(errors)

    if errors:
        print("Validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
