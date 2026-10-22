"""Independent persistent-layer supervision, with bounded crash evidence."""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from root_paths import root_metadata
from dispatch.atomic_io import atomic_write_json
from orchestrator.process_ownership import owned_popen, terminate_owned, ownership_metadata
from orchestrator.layer_heartbeat import read_heartbeat, timestamp

STDERR_LIMIT = 8192
GRACE_SECONDS = 20


def backoff_seconds(exits: int) -> float:
    return min(300, 2 * 2 ** min(8, max(0, exits - 1)))


class StderrTail:
    """Drain pipes continuously so a noisy child cannot block or grow memory."""

    def __init__(self, stream):
        self.data = b""
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._drain, args=(stream,), daemon=True)
        self.thread.start()

    def _drain(self, stream):
        try:
            while chunk := os.read(stream.fileno(), 4096):
                with self.lock:
                    self.data = (self.data + chunk)[-STDERR_LIMIT:]
        except (OSError, ValueError):
            pass
        finally:
            stream.close()

    def text(self):
        with self.lock:
            return self.data.decode("utf-8", errors="replace")


@dataclass
class Child:
    command: list[str]
    heartbeat: Path
    process: object = None
    tail: StderrTail | None = None
    exits: deque = field(default_factory=deque)
    failures: int = 0
    due: float = 0
    started: float = 0
    observed: float = 0
    heartbeat_ticks: int = 0
    token: str = ""
    progress_marker: str | None = None
    progress_observed: float = 0
    exit_started: float | None = None
    status: dict = field(default_factory=lambda: {
        "state": "pending", "alive": False, "ticking": False, "progressing": False,
        "restart_count": 0, "last_restart_at": None, "recovery_seconds": None,
        "last_tick_at": None, "ticks": 0, "last_progress_at": None, "exits": [],
    })


class LayerSupervisor:
    def __init__(self, root: Path, commands: dict[str, list[str]], *,
                 poll_seconds: float = 5, popen=subprocess.Popen,
                 clock: Callable[[], float] = time.monotonic):
        self.root = root
        self.root_audit = root_metadata(root)
        self.path = root / "runtime/dispatch/layer_supervisor/status.json"
        self.children = {
            name: Child(command, self.path.parent / f"{name}.heartbeat.json")
            for name, command in commands.items()
        }
        self.popen = popen
        self.clock = clock
        self.stale_seconds = max(60, 3 * poll_seconds)
        self.stop_requested = False
        previous = read_heartbeat(self.path).get("children", {})
        for name, child in self.children.items():
            old = previous.get(name, {})
            for key in ("restart_count", "last_restart_at", "recovery_seconds", "exits"):
                if key in old:
                    child.status[key] = old[key]
            # Retain audit and breaker across parent restarts; monotonic times
            # themselves are never persisted because their epoch is process-local.
            for evidence in child.status["exits"]:
                try:
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(evidence["exited_at"])).total_seconds()
                    if 0 <= age <= 600:
                        child.exits.append(self.clock() - age)
                except (KeyError, ValueError, TypeError):
                    pass
            if old.get("circuit_open") or old.get("state") == "crash_loop":
                child.status.update(state="crash_loop", circuit_open=True, reason=old.get("reason"))

    def request_stop(self, *_):
        self.stop_requested = True

    def save(self):
        atomic_write_json(self.path, {
            **self.root_audit,
            "updated_at": timestamp(),
            "state": "stopped" if self.stop_requested else "running",
            "children": {name: child.status for name, child in self.children.items()},
        })

    def start(self, child: Child, now: float):
        child.heartbeat.unlink(missing_ok=True)
        child.token = uuid.uuid4().hex
        env = {**os.environ, "AGENTIC_OS_STATE_ROOT": str(self.root.resolve()),
               "AGENTIC_OS_CONFIG_ROOT": self.root_audit["config_root"], "AGENTIC_LAYER_HEARTBEAT": str(child.heartbeat),
               "AGENTIC_LAYER_TOKEN": child.token}
        options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {}
        try:
            child.process = owned_popen(child.command, cwd=self.root, shell=False,
                                       stderr=subprocess.PIPE, env=env, popen=self.popen, **options)
        except OSError as exc:
            self.failed(child, now, None, "launch_failed", str(exc))
            return
        child.status.update(ownership_metadata(child.process))
        child.tail = StderrTail(child.process.stderr) if child.process.stderr else None
        if child.exit_started is not None:
            child.status["restart_count"] += 1
            child.status["last_restart_at"] = timestamp()
        child.started = child.observed = now
        child.heartbeat_ticks = 0
        child.progress_marker = None
        child.status.update(state="starting", pid=child.process.pid, alive=True,
                            ticking=False, progressing=False, last_tick_at=None,
                            last_progress_at=None, ticks=0)

    def terminate(self, child: Child, *, planned: bool = False):
        process = child.process
        if process is None:
            return
        if planned and process.poll() is None:
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
                process.wait(timeout=GRACE_SECONDS)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                pass
        # Also clean up surviving descendants after a graceful root exit.
        terminate_owned(process)
        process.wait(timeout=5)
        if child.tail:
            child.tail.thread.join(timeout=1)

    def failed(self, child: Child, now: float, code: int | None, reason: str, stderr: str):
        child.exits.append(now)
        while child.exits and now - child.exits[0] > 600:
            child.exits.popleft()
        child.failures += 1
        child.exit_started = now
        evidence = {"exit_code": code, "stderr_tail": stderr[-STDERR_LIMIT:],
                    "exited_at": timestamp(), "reason": reason,
                    "started_at": child.status.get("started_at")}
        history = (child.status["exits"] + [evidence])[-20:]
        child.status.update(evidence)
        child.status.update(alive=False, ticking=False, progressing=False, exits=history)
        child.process = None
        if len(child.exits) > 5:
            child.status.update(state="crash_loop", circuit_open=True, reason="more than 5 exits in 600 seconds")
        else:
            delay = backoff_seconds(child.failures)
            child.due = now + delay
            child.status.update(state="backoff", backoff_seconds=delay)

    def step(self):
        now = self.clock()
        for child in self.children.values():
            if self.stop_requested:
                break
            if child.process is None:
                if child.status["state"] != "crash_loop" and now >= child.due:
                    child.status["started_at"] = timestamp()
                    self.start(child, now)
                continue
            code = child.process.poll()
            if code is not None:
                self.terminate(child)
                self.failed(child, now, code, "exited", child.tail.text() if child.tail else "")
                continue
            hb = read_heartbeat(child.heartbeat)
            ticks = hb.get("ticks")
            if hb.get("token") == child.token and isinstance(ticks, int) and ticks > child.heartbeat_ticks:
                child.heartbeat_ticks = ticks
                child.observed = now
                child.status.update({key: hb.get(key) for key in ("ticks", "last_tick_at", "last_progress_at")})
                child.status.update(state="running", ticking=True, heartbeat_pid=hb.get("pid"))
                if child.exit_started is not None:
                    child.status["recovery_seconds"] = now - child.exit_started
                    child.exit_started = None
            progress = child.status.get("last_progress_at")
            if progress and progress != child.progress_marker:
                child.progress_marker = progress
                child.progress_observed = now
            child.status["progressing"] = bool(progress) and now - child.progress_observed <= self.stale_seconds
            if now - child.observed > self.stale_seconds:
                # Persist the classification before attempting potentially slow termination.
                child.status.update(state="hung", ticking=False, reason="stale heartbeat")
                self.save()
                self.terminate(child)
                self.failed(child, self.clock(), child.process.returncode, "hung",
                            child.tail.text() if child.tail else "")
            elif now - child.started > 600:
                child.failures = 0
        self.save()

    def shutdown(self):
        self.stop_requested = True
        for child in self.children.values():
            self.terminate(child, planned=True)
            child.status.update(state="stopped", alive=False, ticking=False, progressing=False,
                                stopped_at=timestamp(),
                                stopped_exit_code=child.process.returncode if child.process else None)
        self.save()

    def run(self):
        previous = {}
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            sig = getattr(signal, name, None)
            if sig is not None:
                previous[sig] = signal.signal(sig, self.request_stop)
        try:
            while not self.stop_requested:
                self.step()
                time.sleep(0.25)
        finally:
            self.shutdown()
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        return 0
