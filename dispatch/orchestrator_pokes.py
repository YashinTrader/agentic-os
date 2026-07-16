"""Notification layer: structured pokes addressed only to the orchestrator.

This module is intentionally separate from the physical supervisor / process
launcher. A successfully written poke is evidence of *notification*, never of
process execution (PID/run records belong to the execution layer).
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dispatch.atomic_io import atomic_create_json

_SAFE_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def poke_dir(repo_root: Path) -> Path:
    return repo_root / "runtime" / "dispatch" / "pokes" / "orchestrator"


def stable_poke_filename(assignment_id: str, event: str) -> str:
    """Deterministic undrained poke name for idempotent completion notifications."""
    safe_a = _SAFE_RE.sub("-", assignment_id.strip()).strip("-") or "assignment"
    safe_e = _SAFE_RE.sub("-", event.strip()).strip("-") or "event"
    return f"{safe_a}__{safe_e}.json"


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def find_active_poke(
    repo_root: Path,
    *,
    assignment_id: str,
    event: str,
) -> dict[str, Any] | None:
    """Return an undrained poke for the same assignment+event if present."""
    root = poke_dir(repo_root)
    if not root.is_dir():
        return None
    stable = root / stable_poke_filename(assignment_id, event)
    if stable.is_file():
        item = _load_json(stable)
        if item is not None:
            item["source_path"] = stable.relative_to(repo_root).as_posix()
            item["idempotent_replay"] = True
            return item
    # Legacy timestamped files (pre-idempotent naming)
    for path in sorted(root.glob("*.json")):
        item = _load_json(path)
        if item is None:
            continue
        if (
            str(item.get("assignment_id", "")) == assignment_id
            and str(item.get("event", "")) == event
            and str(item.get("target", "orchestrator")) in {"orchestrator", "claude"}
        ):
            item["source_path"] = path.relative_to(repo_root).as_posix()
            item["idempotent_replay"] = True
            return item
    return None


def write_orchestrator_poke(
    repo_root: Path,
    *,
    source: str,
    assignment_id: str,
    task_id: str,
    event: str,
    target: str = "orchestrator",
    layer: str = "notification",
) -> tuple[dict[str, Any] | None, list[str]]:
    """Write one structured poke for Claude/orchestrator only.

    Idempotent for an undrained (assignment_id, event) pair: a second write
    returns the existing poke and does not create a duplicate review signal.
    """
    if target not in {"orchestrator", "claude"}:
        return None, ["poke target must be orchestrator"]
    if source.strip().lower() not in {"composer", "grok", "codex", "claude"}:
        return None, ["poke source must be a registered builder or reviewer"]
    if layer != "notification":
        return None, ["pokes belong to the notification layer only"]

    existing = find_active_poke(repo_root, assignment_id=assignment_id, event=event)
    if existing is not None:
        return existing, []

    now = _now()
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "poke_id": f"poke-{uuid.uuid4().hex}",
        "source": source,
        "target": "orchestrator",
        "assignment_id": assignment_id,
        "task_id": task_id,
        "event": event,
        "created_at": now,
        "layer": "notification",
        # Explicit non-execution claim so dashboards/docs cannot confuse layers.
        "is_process_launch": False,
        "is_completion_notification": event.startswith("assignment_"),
    }
    path = poke_dir(repo_root) / stable_poke_filename(assignment_id, event)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        atomic_create_json(path, payload)
    except FileExistsError:
        # Race: another writer won; return that record.
        raced = find_active_poke(repo_root, assignment_id=assignment_id, event=event)
        if raced is not None:
            return raced, []
        return None, [f"failed to create idempotent poke for {assignment_id}/{event}"]
    except OSError as exc:
        return None, [f"failed to write poke: {exc}"]

    payload["source_path"] = path.relative_to(repo_root).as_posix()
    payload["idempotent_replay"] = False
    return payload, []


def list_orchestrator_pokes(repo_root: Path, *, drain: bool = False) -> tuple[list[dict[str, Any]], list[str]]:
    """List (and optionally drain) undrained orchestrator pokes for Claude."""
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    root = poke_dir(repo_root)
    if not root.is_dir():
        return [], []
    for path in sorted(root.glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(item, dict):
                errors.append(f"{path}: root must be object")
                continue
            item["source_path"] = path.relative_to(repo_root).as_posix()
            records.append(item)
            if drain:
                consumed = repo_root / "runtime" / "dispatch" / "pokes" / "consumed" / path.name
                consumed.parent.mkdir(parents=True, exist_ok=True)
                path.replace(consumed)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: {exc}")
    return records, errors
