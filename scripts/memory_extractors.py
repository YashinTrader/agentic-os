#!/usr/bin/env python3
"""Deterministic memory record extractors for Agentic OS.

These extractors build ADR-0007-style records from canonical repo files. They
do not call LLMs, import Cognee, or write to any memory backend.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
DERIVED_NAMESPACE = "system/derived"


def repo_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def stable_event_id(log_path: str, line_number: int, ts: str, event_type: str) -> str:
    digest = hashlib.sha256(f"{log_path}:{line_number}:{ts}:{event_type}".encode("utf-8")).hexdigest()
    return f"memory:episodic:event:{digest}"


def base_record(
    *,
    memory_id: str,
    memory_type: str,
    content: str,
    source: dict[str, Any],
    created_at: str,
    created_by: str,
    refs: dict[str, list[str]],
    confidence: float = 1.0,
) -> dict[str, Any]:
    return {
        "id": memory_id,
        "type": memory_type,
        "namespace": DERIVED_NAMESPACE,
        "content": content,
        "source": source,
        "created_at": created_at,
        "created_by": created_by,
        "confidence": confidence,
        "refs": {
            "tasks": refs.get("tasks", []),
            "adrs": refs.get("adrs", []),
            "events": refs.get("events", []),
            "files": refs.get("files", []),
            "commits": refs.get("commits", []),
            "handoffs": refs.get("handoffs", []),
        },
        "visibility": "shared",
        "status": "active",
        "ttl": None,
        "metadata": {},
    }


def extract_task_entity(path: Path, root: Path = REPO_ROOT) -> dict[str, Any]:
    task = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    task_id = as_text(task.get("id"))
    if not task_id:
        raise ValueError(f"{path}: task id is required")

    title = as_text(task.get("title"))
    status = as_text(task.get("status"))
    owner = as_text(task.get("owner"))
    reviewer = as_text(task.get("reviewer"))
    path_ref = repo_path(path, root)
    depends_on = [as_text(item) for item in (task.get("depends_on") or [])]
    related_decisions = [as_text(item) for item in (task.get("related_decisions") or [])]
    relations = [{"type": "depends_on", "target": item} for item in depends_on]
    relations.extend({"type": "references", "target": item} for item in related_decisions)

    record = base_record(
        memory_id=f"memory:entity:task:{task_id}",
        memory_type="entity",
        content=f"Task {task_id}: {title} (status: {status}, owner: {owner})",
        source={"kind": "task", "path": path_ref, "line": 1, "id": task_id},
        created_at=as_text(task.get("created_at") or task.get("created") or task.get("updated_at")),
        created_by="memory_extractor",
        refs={"tasks": [task_id], "adrs": related_decisions, "files": [path_ref]},
    )
    record.update(
        {
            "entity_type": "task",
            "canonical_id": task_id,
            "name": title,
            "aliases": [],
            "relations": relations,
        }
    )
    record["metadata"] = {
        "task_status": status,
        "owner": owner,
        "reviewer": reviewer,
        "priority": as_text(task.get("priority")),
        "risk_level": as_text(task.get("risk_level")),
        "updated_at": as_text(task.get("updated_at") or task.get("updated")),
    }
    return record


def extract_adr_entity(path: Path, root: Path = REPO_ROOT) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    heading_match = re.search(r"^#\s+(ADR-\d+):\s*(.+)$", text, flags=re.MULTILINE)
    file_match = re.match(r"(ADR-\d+)", path.name)
    adr_id = heading_match.group(1) if heading_match else (file_match.group(1) if file_match else path.stem)
    title = heading_match.group(2).strip() if heading_match else path.stem

    status_match = re.search(r"^-\s*Status:\s*\*{0,2}([^*\n]+?)\*{0,2}\s*$", text, flags=re.MULTILINE)
    date_match = re.search(r"^-\s*Date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$", text, flags=re.MULTILINE)
    status = status_match.group(1).strip().lower() if status_match else "unknown"
    created_at = f"{date_match.group(1)}T00:00:00Z" if date_match else ""
    path_ref = repo_path(path, root)

    record = base_record(
        memory_id=f"memory:entity:adr:{adr_id}",
        memory_type="entity",
        content=f"{adr_id}: {title} (status: {status})",
        source={"kind": "adr", "path": path_ref, "line": 1, "id": adr_id},
        created_at=created_at,
        created_by="memory_extractor",
        refs={"adrs": [adr_id], "files": [path_ref]},
    )
    record.update(
        {
            "entity_type": "adr",
            "canonical_id": adr_id,
            "name": title,
            "aliases": [],
            "relations": [],
        }
    )
    record["metadata"] = {"adr_status": status}
    return record


def extract_event_records(path: Path, root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    path_ref = repo_path(path, root)
    records: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        event = json.loads(raw_line)
        ts = as_text(event.get("ts"))
        event_type = as_text(event.get("type") or event.get("event"))
        actor = as_text(event.get("agent"))
        task_id = as_text(event.get("task_id") or event.get("task"))
        content = as_text(event.get("detail") or event.get("text") or f"{actor} {event_type}")
        event_ref = f"{path_ref}:{line_number}"

        refs: dict[str, list[str]] = {"events": [event_ref], "files": [path_ref]}
        if task_id:
            refs["tasks"] = [task_id]
        if event.get("adr_id"):
            refs["adrs"] = [as_text(event.get("adr_id"))]

        record = base_record(
            memory_id=stable_event_id(path_ref, line_number, ts, event_type),
            memory_type="episodic_event",
            content=content,
            source={"kind": "event_log", "path": path_ref, "line": line_number, "id": event_ref},
            created_at=ts,
            created_by=actor or "unknown",
            refs=refs,
        )
        record.update(
            {
                "event_type": event_type,
                "actor": actor,
                "occurred_at": ts,
                "event_ref": event_ref,
                "task_id": task_id,
                "sequence": line_number,
            }
        )
        record["metadata"] = {
            "legacy_event_field": "type" not in event and "event" in event,
            "ref": event.get("ref"),
        }
        records.append(record)
    return records


def task_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for task_dir in ("tasks/active", "tasks/blocked", "tasks/done"):
        paths.extend(path for path in (root / task_dir).glob("*.yaml") if path.name != "EXAMPLE.yaml")
    return sorted(paths, key=lambda item: repo_path(item, root))


def adr_paths(root: Path) -> list[Path]:
    return sorted((root / "decisions").glob("ADR-*.md"), key=lambda item: repo_path(item, root))


def extract_repo_records(root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    records.extend(extract_task_entity(path, root) for path in task_paths(root))
    records.extend(extract_adr_entity(path, root) for path in adr_paths(root))
    log_path = root / "logs" / "agent-events.jsonl"
    if log_path.exists():
        records.extend(extract_event_records(log_path, root))
    return records


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Extract deterministic memory records from repo files.")
    p.add_argument("--root", default=str(REPO_ROOT), help="Repository root. Defaults to this checkout.")
    p.add_argument("--jsonl", action="store_true", help="Emit one JSON object per line.")
    return p


def main() -> int:
    args = parser().parse_args()
    records = extract_repo_records(Path(args.root))
    try:
        if args.jsonl:
            for record in records:
                print(json.dumps(record, sort_keys=True, separators=(",", ":")))
        else:
            print(json.dumps(records, indent=2, sort_keys=True))
    except BrokenPipeError:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
