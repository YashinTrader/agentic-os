"""Shared wall-clock limits and genuine activity signals for agent runs."""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

from root_paths import resolve_config_root

import yaml


@dataclass(frozen=True)
class DeadlinePolicy:
    startup_seconds: float = 180
    inactivity_seconds: float = 600
    overall_seconds: float = 1800


def adapter_deadlines(repo_root: Path, adapter: str, overall: float) -> DeadlinePolicy:
    reviewer = adapter == "claude-reviewer"
    defaults = (90, 300) if reviewer else (180, 600)
    path = resolve_config_root(repo_root) / "agents" / "run_deadlines.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    config = (data or {}).get(adapter, {})
    values = (float(config.get("startup_seconds", defaults[0])),
              float(config.get("inactivity_seconds", defaults[1])))
    if any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("startup and inactivity limits must be positive")
    return DeadlinePolicy(*values, overall)


class RunDeadlines:
    def __init__(self, policy: DeadlinePolicy, started: float):
        self.policy = policy
        self.started = started
        self.last_activity: float | None = None

    def activity(self, now: float, state, timestamp: str, count: int = 1) -> None:
        self.last_activity = now
        state.startup_activity_at = state.startup_activity_at or timestamp
        state.last_activity_at = timestamp
        state.activity_events += count

    def expired(self, now: float) -> tuple[str, str] | None:
        if self.policy.overall_seconds >= 0 and now - self.started >= self.policy.overall_seconds:
            return "overall", "timed_out"
        if self.last_activity is None:
            if now - self.started >= self.policy.startup_seconds:
                return "startup", "failed_launch"
        elif now - self.last_activity >= self.policy.inactivity_seconds:
            return "inactivity", "stalled"
        return None


def genuine_event(event: object) -> bool:
    if not isinstance(event, dict):
        return False
    kind = event.get("type") or event.get("event")
    if not isinstance(kind, str):
        return False
    if kind == "stream_event":
        return genuine_event(event.get("event"))
    # Session allocation, CLI initialization, heartbeats and process liveness
    # do not establish an accepted model turn.
    if kind in {"turn.started", "turn.completed", "message_start", "message_delta",
                "content_block_start", "content_block_delta", "assistant",
                "tool_use", "tool_result", "token", "model_turn", "tool_execution"}:
        return True
    if kind in {"item.started", "item.updated", "item.completed"}:
        return isinstance(event.get("item"), dict) and event["item"].get("type") in (
            "agent_message", "reasoning", "command_execution", "file_change", "mcp_tool_call")
    return kind == "result" and bool(event.get("result") or event.get("structured_output"))


class StreamActivity:
    """Read only new JSONL bytes; retain incomplete lines until the next poll."""
    def __init__(self, path: Path, *, grok_stream: bool = False):
        self.path = path
        self.grok_stream = grok_stream
        self.liveness_events = 0
        self.offset = 0
        self.pending = b""

    def poll(self) -> int:
        try:
            with self.path.open("rb") as stream:
                if self.path.stat().st_size < self.offset:
                    self.offset = 0
                    self.pending = b""
                stream.seek(self.offset)
                data = stream.read()
                self.offset = stream.tell()
        except OSError:
            return 0
        lines = (self.pending + data).split(b"\n")
        self.pending = lines.pop()
        # Some CLIs write a single complete JSON object without a newline.
        try:
            event = json.loads(self.pending)
        except (ValueError, UnicodeDecodeError):
            pass
        else:
            lines.append(self.pending)
            self.pending = b""
        count = 0
        for line in lines:
            if self.grok_stream and line.strip():
                self.liveness_events += 1
            try:
                event = json.loads(line)
                count += int((isinstance(event, dict) and isinstance(event.get("type"), str))
                             if self.grok_stream else genuine_event(event))
            except (ValueError, UnicodeDecodeError):
                pass
        return count


def worktree_snapshot(root: Path | None, excluded: tuple[Path, ...] = ()) -> dict[str, tuple[int, int]]:
    snapshot = {}
    if root is None:
        return snapshot
    ignored = {".git", "runtime", "node_modules", ".venv", "__pycache__", ".pytest_cache"}
    excluded_paths = {path.resolve() for path in excluded}
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if name not in ignored and not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            try:
                if path.is_symlink() or path.resolve() in excluded_paths or name == ".git":
                    continue
                stat = path.stat()
                snapshot[str(path)] = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                continue
    return snapshot
