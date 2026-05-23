#!/usr/bin/env python3
"""One-shot, idempotent migration from task schema v1 to v2.

The migration follows ADR-0005. It rewrites task YAML files under
tasks/active, tasks/blocked, and tasks/done to v2 field names while preserving
unmapped fields. Running it twice should produce no changes after the first
successful run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]

RENAMES = {
    "created": "created_at",
    "updated": "updated_at",
    "acceptance_criteria": "acceptance",
    "handoff_notes": "notes",
}

STATUS_MAP = {"todo": "ready"}
PRIORITY_MAP = {"P0": "high", "P1": "high", "P2": "medium", "P3": "low"}

CANONICAL_ORDER = [
    "id",
    "title",
    "status",
    "owner",
    "reviewer",
    "created_by",
    "created_at",
    "updated_at",
    "phase",
    "priority",
    "risk_level",
    "requires_human_approval",
    "depends_on",
    "blocks",
    "labels",
    "estimated_effort",
    "related_decisions",
    "objective",
    "context",
    "goals",
    "non_goals",
    "inputs",
    "outputs",
    "constraints",
    "acceptance",
    "human_approval_checklist",
    "notes",
]


def task_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for directory in ("tasks/active", "tasks/blocked", "tasks/done"):
        paths.extend(sorted((root / directory).glob("*.yaml")))
        paths.extend(sorted((root / directory).glob("*.yml")))
    return paths


def infer_phase(task_id: str) -> str:
    if task_id in {"T-0012", "T-0015"}:
        return "1.5"
    return "1"


def normalize_timestamp(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        text = value.isoformat()
        if text.endswith("+00:00"):
            text = text[:-6] + "Z"
        return text
    return value


def default_context(data: dict[str, Any]) -> str:
    objective = str(data.get("objective") or "").strip()
    return objective


def default_goals(data: dict[str, Any]) -> list[str]:
    objective = str(data.get("objective") or "").strip()
    return [objective] if objective else []


def migrate_task(data: dict[str, Any], path: Path) -> dict[str, Any]:
    migrated = dict(data)

    for old, new in RENAMES.items():
        if old in migrated and new in migrated:
            raise ValueError(f"{path}: contains both {old!r} and {new!r}")
        if old in migrated:
            migrated[new] = migrated.pop(old)

    if migrated.get("status") in STATUS_MAP:
        migrated["status"] = STATUS_MAP[migrated["status"]]

    for key in ("created_at", "updated_at"):
        if key in migrated:
            migrated[key] = normalize_timestamp(migrated[key])

    if migrated.get("priority") in PRIORITY_MAP:
        migrated["priority"] = PRIORITY_MAP[migrated["priority"]]
    migrated.setdefault("priority", "medium")

    migrated.setdefault("reviewer", "claude")
    migrated.setdefault("created_by", migrated.get("owner", "codex"))
    migrated.setdefault("phase", infer_phase(str(migrated.get("id", path.stem))))
    migrated.setdefault("context", default_context(migrated))
    migrated.setdefault("goals", default_goals(migrated))
    migrated.setdefault("non_goals", [])
    migrated.setdefault("human_approval_checklist", [])

    if migrated.get("requires_human_approval") and not migrated.get("human_approval_checklist"):
        migrated["human_approval_checklist"] = [
            "Human confirms this task may proceed under its linked ADR or review approval."
        ]

    ordered: dict[str, Any] = {}
    for key in CANONICAL_ORDER:
        if key in migrated:
            ordered[key] = migrated.pop(key)
    for key, value in migrated.items():
        ordered[key] = value
    return ordered


def main() -> int:
    for path in task_paths(ROOT):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path}: task file must contain a YAML mapping")
        migrated = migrate_task(data, path)
        text = yaml.safe_dump(migrated, sort_keys=False, allow_unicode=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
