"""Append-only local poke queue addressed only to the orchestrator."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dispatch.atomic_io import atomic_write_json


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def poke_dir(repo_root: Path) -> Path:
    return repo_root / "runtime" / "dispatch" / "pokes" / "orchestrator"


def write_orchestrator_poke(repo_root: Path, *, source: str, assignment_id: str, task_id: str, event: str, target: str = "orchestrator") -> tuple[dict[str, Any] | None, list[str]]:
    if target not in {"orchestrator", "claude"}:
        return None, ["poke target must be orchestrator"]
    if source.strip().lower() not in {"composer", "grok", "codex", "claude"}:
        return None, ["poke source must be a registered builder or reviewer"]
    payload = {
        "schema_version": "1.0",
        "poke_id": f"poke-{uuid.uuid4().hex}",
        "source": source,
        "target": "orchestrator",
        "assignment_id": assignment_id,
        "task_id": task_id,
        "event": event,
        "created_at": _now(),
    }
    path = poke_dir(repo_root) / f"{payload['created_at'].replace(':', '')}-{payload['poke_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)
    payload["source_path"] = path.relative_to(repo_root).as_posix()
    return payload, []


def list_orchestrator_pokes(repo_root: Path, *, drain: bool = False) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted(poke_dir(repo_root).glob("*.json")) if poke_dir(repo_root).is_dir() else []:
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            item["source_path"] = path.relative_to(repo_root).as_posix()
            records.append(item)
            if drain:
                consumed = repo_root / "runtime" / "dispatch" / "pokes" / "consumed" / path.name
                consumed.parent.mkdir(parents=True, exist_ok=True)
                path.replace(consumed)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: {exc}")
    return records, errors
