"""Write daemon discovery artifacts to runtime/ and append audit events."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def inventory_path(root: Path) -> Path:
    return root / "runtime" / "registry" / "cli_inventory.yaml"


def status_path(root: Path) -> Path:
    return root / "runtime" / "status" / "daemon_status.json"


def write_inventory(root: Path, inventory: dict[str, Any]) -> Path:
    path = inventory_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        yaml.safe_dump(
            inventory,
            handle,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
    return path


def write_daemon_status(
    root: Path,
    *,
    mode: str,
    inventory: dict[str, Any],
    errors: list[str] | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> Path:
    path = status_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = inventory.get("summary", {})
    status = {
        "schema_version": "1.0",
        "daemon": "agentic-os-cli-discovery",
        "mode": mode,
        "status": "error" if errors else "ok",
        "started_at": started_at or inventory.get("generated_at") or utc_now(),
        "finished_at": finished_at or inventory.get("generated_at") or utc_now(),
        "last_run_at": inventory.get("generated_at"),
        "inventory_path": inventory_path(root).relative_to(root).as_posix(),
        "summary": summary,
        "errors": errors or [],
    }
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(status, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return path


def append_discovery_event(
    root: Path,
    inventory: dict[str, Any],
    *,
    mode: str,
    task_id: str = "T-DAEMON-001",
) -> Path:
    """Append a note event describing the discovery run."""
    log_path = root / "logs" / "agent-events.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    summary = inventory.get("summary", {})
    event = {
        "ts": inventory.get("generated_at") or utc_now(),
        "agent": "daemon",
        "type": "note",
        "task_id": task_id,
        "detail": (
            f"CLI discovery run ({mode}): "
            f"{summary.get('available', 0)}/{summary.get('total', 0)} tools available"
        ),
        "text": (
            "Runtime daemon completed CLI inventory refresh. "
            f"Available={summary.get('available', 0)}, "
            f"Missing={summary.get('missing', 0)}."
        ),
        "ref": "runtime/registry/cli_inventory.yaml",
    }
    with log_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n")
    return log_path