"""Local, adapter-declared wake delivery for assignment builders."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from dispatch.atomic_io import atomic_write_json


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class WakeOutcome:
    state: str
    delivered: bool
    mechanism: str
    detail: str
    woken_at: str | None = None
    signal_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_wake_config(repo_root: Path, adapter_id: str) -> dict[str, Any]:
    adapter_file = repo_root / "agents" / f"{adapter_id.replace('-', '_')}_adapter.yaml"
    if adapter_file.is_file():
        data = yaml.safe_load(adapter_file.read_text(encoding="utf-8")) or {}
        if isinstance(data.get("wake"), dict):
            return dict(data["wake"])
    registry = yaml.safe_load((repo_root / "agents" / "adapter_registry.yaml").read_text(encoding="utf-8")) or {}
    for adapter in registry.get("adapters", []):
        if adapter.get("id") == adapter_id and isinstance(adapter.get("wake"), dict):
            return dict(adapter["wake"])
    return {}


def _queue_signal(repo_root: Path, agent_id: str, payload: dict[str, Any]) -> str:
    target = repo_root / "runtime" / "dispatch" / "wake_queue" / agent_id / f"{payload['assignment_id']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target, payload)
    return target.relative_to(repo_root).as_posix()


def request_agent_wake(
    repo_root: Path,
    *,
    assignment_id: str,
    task_id: str,
    agent_id: str,
    adapter_id: str,
    task_path: str,
    requested_by: str,
) -> WakeOutcome:
    """Deliver a bounded local wake signal; never launches a new execution surface."""
    if requested_by.strip().lower() != "claude":
        return WakeOutcome("wake_rejected", False, "none", "only claude may request wakes")

    config = _load_wake_config(repo_root, adapter_id)
    mechanism = str(config.get("mechanism") or "unknown")
    if not config.get("enabled", False):
        return WakeOutcome("pending_wake", False, mechanism, "wake mechanism is disabled")

    payload = {
        "schema_version": "1.0",
        "assignment_id": assignment_id,
        "task_id": task_id,
        "agent_id": agent_id,
        "adapter_id": adapter_id,
        "task_path": task_path,
        "mechanism": mechanism,
        "requested_by": requested_by,
        "requested_at": utc_now(),
    }
    if mechanism in {"assignment_watcher", "physical_supervisor"}:
        signal_path = _queue_signal(repo_root, agent_id, payload)
        detail = (
            "physical supervisor wake queued"
            if mechanism == "physical_supervisor"
            else "watcher signal queued"
        )
        return WakeOutcome("wake_delivered", True, mechanism, detail, utc_now(), signal_path)

    if mechanism == "codex_local_builder":
        path = (repo_root / task_path).resolve()
        try:
            from dispatch.codex_local_builder_gate import evaluate_worker_task_eligibility
            from orchestrator.loaders import load_task_yaml

            task = load_task_yaml(path)
            eligible, reason = evaluate_worker_task_eligibility(repo_root, task, has_active_claim=False)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            return WakeOutcome("pending_wake", False, mechanism, f"task eligibility unavailable: {exc}")
        if not eligible:
            return WakeOutcome("pending_wake", False, mechanism, f"task is not worker-eligible: {reason}")
        signal_path = _queue_signal(repo_root, agent_id, payload)
        return WakeOutcome("wake_delivered", True, mechanism, "eligible task queued for existing local-builder worker", utc_now(), signal_path)

    return WakeOutcome("pending_wake", False, mechanism, f"unsupported wake mechanism: {mechanism}")


def read_wake_signal(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
