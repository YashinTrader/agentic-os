"""File-based persistence for orchestrator runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{stamp}-{uuid4().hex[:8]}"


def orchestrator_root(repo_root: Path) -> Path:
    return repo_root / "runtime" / "orchestrator"


def run_dir(repo_root: Path, run_id: str, output_dir: str | None = None) -> Path:
    if output_dir:
        return Path(output_dir) / run_id
    return orchestrator_root(repo_root) / "runs" / run_id


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def save_state(run_dir_path: Path, state: dict[str, Any], dry_run: bool) -> str:
    path = run_dir_path / "state.json"
    if not dry_run:
        run_dir_path.mkdir(parents=True, exist_ok=True)
        serializable = _json_safe(dict(state))
        path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def save_latest(repo_root: Path, state: dict[str, Any], plan: dict[str, Any], dry_run: bool) -> tuple[str, str]:
    root = orchestrator_root(repo_root)
    state_path = root / "latest_state.json"
    plan_path = root / "latest_plan.json"
    if not dry_run:
        root.mkdir(parents=True, exist_ok=True)
        (root / "runs").mkdir(exist_ok=True)
        state_path.write_text(json.dumps(_json_safe(dict(state)), indent=2, ensure_ascii=False), encoding="utf-8")
        plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(state_path), str(plan_path)


def save_failed_latest(repo_root: Path, state: dict[str, Any], dry_run: bool) -> str:
    """Persist error-only orchestrator state without a plan."""
    root = orchestrator_root(repo_root)
    state_path = root / "latest_state.json"
    if not dry_run:
        root.mkdir(parents=True, exist_ok=True)
        failed = dict(state)
        failed["plan_path"] = None
        failed["context_pack_path"] = None
        failed["next_action"] = failed.get("next_action") or "fix_task_input"
        state_path.write_text(json.dumps(_json_safe(failed), indent=2, ensure_ascii=False), encoding="utf-8")
        plan_path = root / "latest_plan.json"
        if plan_path.exists():
            plan_path.unlink()
    return str(state_path)


def append_orchestration_event(repo_root: Path, state: dict[str, Any], dry_run: bool, no_log: bool) -> None:
    if dry_run or no_log or state.get("errors"):
        return
    log_path = repo_root / "logs" / "agent-events.jsonl"
    event = {
        "ts": utc_now(),
        "agent": "orchestrator",
        "task_id": state.get("task_id", ""),
        "type": "orchestration_planned",
        "detail": (
            f"orchestration plan generated run_id={state.get('run_id')} "
            f"team={state.get('selected_team')} approval={state.get('approval_level')}"
        ),
        "ref": state.get("plan_path", ""),
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")