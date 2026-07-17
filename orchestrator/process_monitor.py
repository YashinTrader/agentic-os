"""Monitor launched agent processes: heartbeat, completion, orphan recovery."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from orchestrator.runtime_store import (
    STATE_ORPHANED,
    STATE_RUNNING,
    STATE_TIMED_OUT,
    RunState,
    save_run_state,
    utc_now,
)

PollFn = Callable[[Any], int | None]


@dataclass
class MonitorResult:
    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str
    orphaned: bool = False


def _default_poll(process: Any) -> int | None:
    return process.poll()


def _default_wait(process: Any, timeout: float | None) -> int:
    return int(process.wait(timeout=timeout))


def read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def monitor_process(
    process: Any,
    *,
    state: RunState,
    repo_root: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
    heartbeat_seconds: float = 2.0,
    poll_fn: PollFn | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    kill_fn: Callable[[Any], None] | None = None,
) -> MonitorResult:
    """Block until process exits or times out; keep heartbeat fresh.

    State must already be `running` with a real PID recorded before calling.
    """
    if state.process_state != STATE_RUNNING or not state.pid:
        raise ValueError("monitor_process requires running state with PID")

    poll = poll_fn or _default_poll
    sleep = sleep_fn or time.sleep
    started = time.monotonic()
    exit_code: int | None = None
    timed_out = False

    while True:
        code = poll(process)
        state.heartbeat_at = utc_now()
        save_run_state(repo_root, state)
        if code is not None:
            exit_code = int(code)
            break
        elapsed = time.monotonic() - started
        # timeout_seconds == 0 means immediate timeout (tests / hard stop).
        if timeout_seconds >= 0 and elapsed >= timeout_seconds:
            timed_out = True
            if kill_fn is not None:
                kill_fn(process)
            else:
                try:
                    process.kill()
                except OSError:
                    pass
                try:
                    exit_code = int(process.wait(timeout=5))
                except Exception:
                    exit_code = None
            break
        sleep(max(0.05, heartbeat_seconds))

    return MonitorResult(
        exit_code=exit_code,
        timed_out=timed_out,
        stdout=read_text(stdout_path),
        stderr=read_text(stderr_path),
        orphaned=False,
    )


def classify_orphan(state: RunState, *, process_alive: bool | None) -> str | None:
    """Return orphaned state if a run looks abandoned."""
    if state.process_state not in {STATE_RUNNING, "launching"}:
        return None
    if process_alive is False:
        return STATE_ORPHANED
    if state.pid and process_alive is None:
        # Unknown liveness — leave running, but surface orphaned only when proven dead.
        return None
    return None


def mark_orphaned(repo_root: Path, state: RunState, *, detail: str = "process missing") -> RunState:
    state.process_state = STATE_ORPHANED
    state.completed_at = utc_now()
    state.blocked_reason = detail
    state.retry_eligible = False
    save_run_state(repo_root, state)
    return state


def pid_is_alive(pid: int) -> bool | None:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if process:
                ctypes.windll.kernel32.CloseHandle(process)
                return True
            return True if ctypes.get_last_error() == 5 else False
        except (AttributeError, OSError, SystemError):
            return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, SystemError):
        return None
