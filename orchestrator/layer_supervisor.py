"""Independent persistent-layer supervision, with bounded crash evidence."""
from __future__ import annotations

import os
import copy
import random
import signal
import subprocess
import threading
import time
import traceback
import uuid
from collections import deque
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from root_paths import root_metadata
from dispatch.atomic_io import atomic_write_json
from orchestrator.process_ownership import owned_popen, terminate_owned, ownership_metadata, process_start_time
from orchestrator.builder_dispatch import dispatch_status
from orchestrator.layer_heartbeat import read_heartbeat, timestamp
from orchestrator.supervisor_control import control_dir, file_lock, identity_state, register_supervisor_job, is_legacy_status, recorded_state

from orchestrator.launch_failures import classify_launch_failure, executable_identity, alert_once
from orchestrator.root_restart_guard import RootRestartGuard

BACKOFF_FLOOR = 2
BACKOFF_CAP = 300
PROBE_COOLDOWN = 15 * 60
PROBE_CAP = 4 * 3600
IDENTITY_CHECK_SECONDS = 60
LIVENESS_SECONDS = 30
PARKED_LIVENESS_SECONDS = 60
HEARTBEAT_STATUS_SECONDS = 5
STDERR_LIMIT = 8192
GRACE_SECONDS = 20


def backoff_seconds(exits: int) -> float:
    return min(BACKOFF_CAP, BACKOFF_FLOOR * 2 ** min(8, max(0, exits - 1)))


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
    identity_cache: dict | None = None
    identity_check_due: float = 0
    probe_due: float = 0
    cooldown: float = 0
    probing: bool = False
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
        "failure_class": None, "blocked_executable": None, "next_probe_at": None,
    })


class LayerSupervisor:
    def __init__(self, root: Path, commands: dict[str, list[str]], *,
                 poll_seconds: float = 5, popen=subprocess.Popen,
                 clock: Callable[[], float] = time.monotonic, rng=None,
                 wall_clock=time.time, root_guard: bool = False):
        self.rng = rng or random.Random()
        self.wall_clock = wall_clock
        self.root_guard = RootRestartGuard(root, wall_clock) if root_guard else None
        self.guard_started = False
        self.healthy_since = None
        self.health_recorded = False
        self.alerts = []
        self._saved_content = None
        self._saved_at = float('-inf')
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
        self.shutdown_complete = False
        self.instance_token = uuid.uuid4().hex
        self.stop_request = None
        self.recorded_children = []
        self.supervisor_errors = []
        self.supervisor_error_count = 0
        self.identity = {"pid": os.getpid(), "process_start_time": process_start_time(os.getpid()),
                         "instance_token": self.instance_token}
        previous_status = read_heartbeat(self.path)
        self.alerts = previous_status.get("alerts", [])
        previous = previous_status.get("children", {})
        for name, child in self.children.items():
            old = previous.get(name, {})
            for key in ("restart_count", "last_restart_at", "recovery_seconds", "exits",
                        "failure_class", "blocked_executable", "next_probe_at", "probe_cooldown", "reset_token"):
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
                state = {"CONFIG": "blocked_config", "BLOCKED_SECURITY_POLICY": "blocked_security_policy"}.get(
                    old.get("failure_class"), "crash_loop")
                child.status.update(state=state, circuit_open=True, reason=old.get("reason"))
                child.cooldown = old.get("probe_cooldown", PROBE_COOLDOWN)
                remaining = max(0, (old.get("next_probe_at") or self.wall_clock() + child.cooldown) - self.wall_clock())
                child.probe_due = self.clock() + remaining
                child.identity_check_due = self.clock() + IDENTITY_CHECK_SECONDS

    def request_stop(self, *_):
        self.stop_requested = True

    def parked(self):
        return bool(self.children) and all(c.status.get("circuit_open") and c.process is None
                                           for c in self.children.values())

    def sleep_seconds(self):
        if self.parked():
            return 5
        return .25 if any(c.status['state'] == 'starting' for c in self.children.values()) else 1

    def add_alert(self, key, **payload):
        identifier = alert_once(self.root, key, **payload)
        if identifier not in self.alerts:
            self.alerts.append(identifier)

    def save(self):
        state = "stopping" if self.stop_requested else "running"
        if self.shutdown_complete:
            state = "stopped_by_request" if self.stop_request else "stopped"
        parked_reason = None
        if self.parked() and not self.stop_requested:
            state = "parked"
            parked_reason = "all children have open circuits or deterministic launch failures"
            self.add_alert(['root_parked'], kind='root_parked', action='Inspect child alerts and remediate before resetting circuits.')
        content = {
            **self.root_audit,
            **self.identity,
            "builder_dispatch": dispatch_status(self.root),
            "state": state,
            "alerts": self.alerts, "parked_reason": parked_reason,
            "stop_request": self.stop_request,
            "recorded_children": self.recorded_children,
            "supervisor_errors": self.supervisor_errors,
            "supervisor_error_count": self.supervisor_error_count,
            "children": {name: child.status for name, child in self.children.items()},
        }
        interval = PARKED_LIVENESS_SECONDS if state == "parked" else LIVENESS_SECONDS
        changed = content != self._saved_content
        elapsed = self.clock() - self._saved_at
        if changed and self._saved_content is not None and elapsed < HEARTBEAT_STATUS_SECONDS:
            # Ticking idle children can publish every second. Batch only their
            # counters/timestamps; state, progress, failures and controls stay immediate.
            def significant(document):
                document = copy.deepcopy(document)
                for status in document['children'].values():
                    status.pop('ticks', None)
                    status.pop('last_tick_at', None)
                return document
            changed = significant(content) != significant(self._saved_content)
        if changed or elapsed >= interval:
            atomic_write_json(self.path, {**content, "updated_at": timestamp()})
            self._saved_content = copy.deepcopy(content)
            self._saved_at = self.clock()

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
            self.failed(child, now, None, "launch_failed", str(exc), exc=exc)
            return
        child.status.update(ownership_metadata(child.process))
        self.recorded_children.append({"pid": child.process.pid, **ownership_metadata(child.process), "failure_class": None})
        child.tail = StderrTail(child.process.stderr) if child.process.stderr else None
        if child.exit_started is not None:
            child.status["restart_count"] += 1
            child.status["last_restart_at"] = timestamp()
        child.started = child.observed = now
        child.heartbeat_ticks = 0
        child.progress_marker = None
        child.status.update(state="starting", pid=child.process.pid, alive=True,
                            ticking=False, progressing=False, last_tick_at=None,
                            last_progress_at=None, ticks=0, heartbeat_pid=None,
                            heartbeat_process_start_time=None)

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
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.status.update(state="terminating", alive=True, ticking=False, progressing=False,
                                terminating_pid=process.pid,
                                terminating_process_start_time=child.status.get("process_start_time"))
            child.status.setdefault("terminating_at", timestamp())
            return False
        if child.tail:
            child.tail.thread.join(timeout=1)
        child.status.pop("terminating_at", None)
        return True

    def failed(self, child: Child, now: float, code: int | None, reason: str, stderr: str, exc=None):
        child.exits.append(now)
        while child.exits and now - child.exits[0] > 600:
            child.exits.popleft()
        child.failures += 1
        child.exit_started = now
        failure_class = classify_launch_failure(exc, stderr)
        evidence = {"failure_class": failure_class, "exit_code": code, "stderr_tail": stderr[-STDERR_LIMIT:],
                    "exited_at": timestamp(), "reason": reason,
                    "started_at": child.status.get("started_at")}
        history = (child.status["exits"] + [evidence])[-20:]
        child.status.update(evidence)
        child.status.update(alive=False, ticking=False, progressing=False, exits=history)
        child.process = None
        if failure_class in {"BLOCKED_SECURITY_POLICY", "CONFIG"}:
            identity = executable_identity(child.command[0], self.root)
            child.status.update(state="blocked_security_policy" if failure_class == "BLOCKED_SECURITY_POLICY" else "blocked_config",
                                circuit_open=True, blocked_executable=identity, next_probe_at=None)
            child.probing = False
            child.identity_check_due = now + IDENTITY_CHECK_SECONDS
            name = next(name for name, value in self.children.items() if value is child)
            self.add_alert([name, identity['path'], identity['sha256']], layer=name,
                           failure_class=failure_class, blocked_executable=identity,
                           action="switch to a permitted signed runtime or ask the operator; do not disable Smart App Control"
                           if failure_class == "BLOCKED_SECURITY_POLICY" else "Restore the missing executable or ask the operator.")
        elif len(child.exits) > 5 or child.probing:
            child.cooldown = min(PROBE_CAP, child.cooldown * 2) if child.cooldown else PROBE_COOLDOWN
            child.probe_due = now + child.cooldown
            child.probing = False
            child.status.update(next_probe_at=self.wall_clock() + child.cooldown, probe_cooldown=child.cooldown)
            child.status.update(state="crash_loop", circuit_open=True, reason="more than 5 exits in 600 seconds")
        else:
            delay = self.rng.uniform(BACKOFF_FLOOR, backoff_seconds(child.failures))
            child.due = now + delay
            child.status.update(state="backoff", backoff_seconds=delay)

    def step(self):
        request = read_heartbeat(self.path.parent / "stop_request.json")
        if (request.get("instance_token") == self.instance_token
                and all(request.get(key) for key in ("requester", "reason", "token", "at"))):
            self.stop_request = request
            self.request_stop()
        now = self.clock()
        for name, child in self.children.items():
            if self.stop_requested:
                break
            try:
                self.supervise_child(child, now)
            except Exception as exc:
                self.record_error(name=name, child=child, exc=exc)
        if self.root_guard and self.guard_started and not self.health_recorded:
            if all(c.status['state'] == 'running' for c in self.children.values()):
                if self.healthy_since is None:
                    self.healthy_since = now
                if now - self.healthy_since >= 600:
                    with file_lock(self.path.parent / 'control.lock'):
                        self.root_guard.healthy()
                    self.health_recorded = True
            else:
                self.healthy_since = None
        self.save()

    def record_error(self, *, name, child, exc):
        evidence = {"at": timestamp(), "child": name, "error": str(exc),
                    "traceback_tail": traceback.format_exc()[-STDERR_LIMIT:]}
        self.supervisor_error_count += 1
        self.supervisor_errors = (self.supervisor_errors + [evidence])[-20:]
        child.status["supervisor_error_count"] = child.status.get("supervisor_error_count", 0) + 1
        child.status["supervisor_error"] = evidence
        # Feed the same rolling breaker without discarding a live owned process.
        process = child.process
        self.failed(child, self.clock(), None, "supervision_error", evidence["traceback_tail"])
        child.process = process
        if process is not None:
            child.status.update(state="terminating", alive=True, terminating_pid=process.pid,
                                terminating_process_start_time=child.status.get("process_start_time"))
            child.status.setdefault("terminating_at", timestamp())

    def supervise_child(self, child, now):
        if child.status.get("circuit_open") and child.process is not None:
            if self.terminate(child):
                child.status.update(state="crash_loop", alive=False)
                child.process = None
            return
        if child.status.get("state") == "terminating":
            if not self.terminate(child):
                return
            self.failed(child, now, child.process.returncode, child.status.get("reason", "hung"),
                        child.tail.text() if child.tail else "")
            return
        if child.process is None:
            if child.status.get('circuit_open'):
                name = next(name for name, value in self.children.items() if value is child)
                reset = read_heartbeat(self.path.parent / 'circuit_resets' / (name + '.json'))
                allow = (reset.get('token') and reset.get('token') != child.status.get('reset_token')
                         and all(reset.get(k) for k in ('requester', 'reason', 'at')))
                if allow:
                    child.status['reset_token'] = reset['token']
                elif child.status.get('failure_class') in {'BLOCKED_SECURITY_POLICY', 'CONFIG'}:
                    if now < child.identity_check_due:
                        return
                    child.identity_check_due = now + IDENTITY_CHECK_SECONDS
                    old = child.status.get('blocked_executable') or {}
                    current = executable_identity(child.command[0], self.root, child.identity_cache or old)
                    child.identity_cache = current
                    allow = (current['sha256'] is not None if child.status['failure_class'] == 'CONFIG'
                             else current['path'] != old.get('path') or
                             current['sha256'] is not None and current['sha256'] != old.get('sha256'))
                else:
                    allow = now >= child.probe_due
                if not allow:
                    return
                child.probing = True
                child.status.update(circuit_open=False, next_probe_at=None, state='half_open')
                child.due = now
            if now >= child.due:
                child.status["started_at"] = timestamp()
                self.start(child, now)
            return
        code = child.process.poll()
        if code is not None:
            if not self.terminate(child):
                return
            self.failed(child, now, code, "exited", child.tail.text() if child.tail else "")
            return
        hb = read_heartbeat(child.heartbeat)
        ticks = hb.get("ticks")
        if hb.get("token") == child.token and isinstance(ticks, int) and ticks > child.heartbeat_ticks:
            child.heartbeat_ticks = ticks
            child.observed = now
            child.status.update({key: hb.get(key) for key in ("ticks", "last_tick_at", "last_progress_at")})
            child.status.update(state="running", ticking=True, heartbeat_pid=hb.get("pid"))
            heartbeat_pid = hb.get("pid")
            if type(heartbeat_pid) is int and heartbeat_pid > 0:
                start = process_start_time(heartbeat_pid)
                child.status["heartbeat_process_start_time"] = start
                identity = {"pid": heartbeat_pid, "process_start_time": start}
                # Windows venv shims and their interpreters have different
                # PIDs. Retain both identities for external exit verification.
                if start and identity not in self.recorded_children:
                    self.recorded_children.append(identity)
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
            child.status.update(state="hung", ticking=False, reason="hung")
            self.save()
            if not self.terminate(child):
                return
            self.failed(child, self.clock(), child.process.returncode, "hung",
                        child.tail.text() if child.tail else "")
        elif now - child.started > 600:
            child.failures = 0
            child.cooldown = 0
            child.probing = False
            child.status.update(circuit_open=False, next_probe_at=None)

    def shutdown(self, *, planned=True):
        self.stop_requested = True
        for child in self.children.values():
            try:
                gone = self.terminate(child, planned=True)
            except Exception as exc:
                self.record_error(name=next(name for name, value in self.children.items() if value is child),
                                  child=child, exc=exc)
                continue
            if gone is False:
                continue
            child.status.update(state="stopped", alive=False, ticking=False, progressing=False,
                                stopped_at=timestamp(),
                                stopped_exit_code=child.process.returncode if child.process else None)
        if (planned and self.root_guard and self.guard_started
                and all(not c.status.get('alive') for c in self.children.values())):
            with file_lock(self.path.parent / 'control.lock'):
                self.root_guard.planned_stop()
        self.shutdown_complete = True
        self.save()

    def run(self):
        try:
            with file_lock(self.path.parent / "instance.lock"):
                with file_lock(self.path.parent / "control.lock"):
                    if (control_dir(self.root) / "maintenance.json").exists():
                        print("maintenance mode: supervisor not started", flush=True)
                        return 0
                    old = read_heartbeat(self.path)
                    if is_legacy_status(old):
                        print(f'legacy supervisor status requires audited adoption: python scripts/stop_supervisor.py --state-root "{self.root}" --adopt-legacy-status --actor <a> --reason <r>', flush=True)
                        return 2
                    if old and recorded_state(old, self.root) in {"live", "unknown", "unverified"}:
                        print("supervisor already live or identity unverifiable; refusing start", flush=True)
                        return 2
                    if self.root_guard:
                        if not self.root_guard.start():
                            print("root restart guard open; start refused", flush=True)
                            return 78
                        self.guard_started = True
                    job_name, self._root_job = register_supervisor_job()
                    self.identity["process_identity"] = job_name
                    self.save()
                return self._run()
        except OSError as exc:
            print(f"supervisor start/control refused: {exc}", flush=True)
            return 2

    def _run(self):
        previous = {}
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            sig = getattr(signal, name, None)
            if sig is not None:
                previous[sig] = signal.signal(sig, self.request_stop)
        try:
            while not self.stop_requested:
                try:
                    self.step()
                except Exception as exc:
                    self.supervisor_error_count += 1
                    self.supervisor_errors = (self.supervisor_errors + [{
                        "at": timestamp(), "child": None, "error": str(exc),
                        "traceback_tail": traceback.format_exc()[-STDERR_LIMIT:],
                    }])[-20:]
                time.sleep(self.sleep_seconds())
        finally:
            self.shutdown(planned=self.stop_requested)
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        return 0
