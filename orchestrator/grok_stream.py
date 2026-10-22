"""Terminal metadata from Grok's streaming-json ACP updates."""
from __future__ import annotations

import json


def terminal_event(stdout: str) -> dict | None:
    terminal = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "end":
            terminal = event
    return terminal


def record_terminal(state, stdout: str) -> None:
    event = terminal_event(stdout)
    if event is None:
        return
    session = event.get("sessionId")
    state.session_id = session if isinstance(session, str) else None
    reason = event.get("stopReason")
    state.stop_reason = reason if isinstance(reason, str) else None
    usage = event.get("usage")
    state.token_usage = {
        key: usage[key] for key in ("input_tokens", "output_tokens", "total_tokens")
        if isinstance(usage, dict) and type(usage.get(key)) is int and usage[key] >= 0
    }
