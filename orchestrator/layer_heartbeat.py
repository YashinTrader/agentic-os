"""Cooperative layer heartbeat: ticks prove loop activity; progress proves work."""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from dispatch.atomic_io import atomic_write_json

_ticks = 0
_last_progress = None
_last_write = 0.0
_last_warning = None
_stop_requested = False


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def tick(*, progress: bool = False) -> None:
    """Called by work/poll loops, never by an unconditional background thread."""
    global _ticks, _last_progress, _last_write, _last_warning
    if _stop_requested:
        raise SystemExit(0)
    path = os.environ.get("AGENTIC_LAYER_HEARTBEAT")
    if not path:
        return
    now = time.monotonic()
    if progress:
        _last_progress = timestamp()
    if not progress and now - _last_write < 1:
        return
    _ticks += 1
    try:
        atomic_write_json(Path(path), {
            "pid": os.getpid(), "token": os.environ.get("AGENTIC_LAYER_TOKEN"), "last_tick_at": timestamp(), "ticks": _ticks,
            "last_progress_at": _last_progress,
        })
    except OSError as exc:
        if _last_warning is None or now - _last_warning >= 60:
            logging.getLogger(__name__).warning('Layer heartbeat write deferred: %.300s', exc)
            _last_warning = now
    _last_write = now


def read_heartbeat(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def request_stop(*_):
    global _stop_requested
    _stop_requested = True


def install_stop_handlers():
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            signal.signal(sig, request_stop)


def wait_with_heartbeat(process, timeout: float):
    deadline = time.monotonic() + timeout
    while True:
        tick()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            return process.wait(timeout=min(2, remaining))
        except subprocess.TimeoutExpired:
            if time.monotonic() >= deadline:
                raise
