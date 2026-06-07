"""Load task and registry data for orchestration."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


def safe_task_path(repo_root: Path, task_arg: str) -> Path:
    """Resolve task path under repo; reject traversal."""
    candidate = Path(task_arg)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (repo_root / candidate).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ValueError(f"task path must be inside repository: {task_arg}") from exc
    tasks_root = (repo_root / "tasks").resolve()
    try:
        resolved.relative_to(tasks_root)
    except ValueError as exc:
        raise ValueError(f"task path must be under tasks/: {task_arg}") from exc
    if not resolved.exists():
        raise FileNotFoundError(f"task file not found: {resolved}")
    return resolved


def load_task_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a YAML mapping")
    return data


def load_registry_list(repo_root: Path, rel_path: str, key: str) -> list[dict[str, Any]]:
    path = repo_root / rel_path
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get(key), list):
            return [x for x in data[key] if isinstance(x, dict)]
    except Exception:
        pass
    return []


def load_team_by_id(repo_root: Path, team_id: str) -> dict[str, Any] | None:
    for team in load_registry_list(repo_root, "teams/registry.yaml", "teams"):
        if str(team.get("id")) == team_id:
            return team
    return None


def load_handoffs_for_task(repo_root: Path, task_id: str, limit: int = 5) -> list[dict[str, str]]:
    handoffs_dir = repo_root / "handoffs"
    if not handoffs_dir.exists():
        return []
    matches: list[tuple[float, dict[str, str]]] = []
    for path in handoffs_dir.glob("*.md"):
        if path.name == "README.md":
            continue
        if task_id not in path.name:
            continue
        matches.append(
            (
                path.stat().st_mtime,
                {"path": str(path.relative_to(repo_root)), "name": path.name, "preview": path.read_text(encoding="utf-8")[:500]},
            )
        )
    matches.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in matches[:limit]]


def load_events_for_task(repo_root: Path, task_id: str, limit: int = 20) -> list[dict[str, Any]]:
    log_path = repo_root / "logs" / "agent-events.jsonl"
    if not log_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and str(row.get("task") or row.get("task_id", "")) == task_id:
            events.append(row)
    return events[-limit:]


def normalize_tokens(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[a-zA-Z][a-zA-Z0-9_./-]*", text.lower())}


def collect_file_paths_from_task(task: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    for field in ("inputs", "outputs"):
        value = task.get(field, [])
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and ("/" in item or "\\" in item):
                    paths.add(item)
        elif isinstance(value, str) and ("/" in value or "\\" in value):
            paths.add(value)
    return paths