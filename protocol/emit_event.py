"""Append canonical events to logs/agent-events.jsonl."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from protocol.event_types import ALLOWED_EVENT_TYPES


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def append_event(
    root: Path,
    *,
    agent: str,
    event_type: str,
    task_id: str | None = None,
    detail: str | None = None,
    text: str | None = None,
    ref: str | None = None,
    ts: str | None = None,
) -> Path:
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError(f"event type {event_type!r} is not in canonical vocabulary")

    event: dict[str, Any] = {
        "ts": ts or utc_now(),
        "agent": agent,
        "type": event_type,
    }
    if task_id:
        event["task_id"] = task_id
    if detail:
        event["detail"] = detail
    if text:
        event["text"] = text
    if ref:
        event["ref"] = ref

    log_path = root / "logs" / "agent-events.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n")
    return log_path