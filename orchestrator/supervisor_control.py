"""Local supervisor control, identity fencing and startup serialization."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import signal
import time

from orchestrator.layer_heartbeat import read_heartbeat

from orchestrator.process_ownership import process_start_time


def register_supervisor_job() -> tuple[str | None, object]:
    """A named Job lets another console terminate this exact tree by handle."""
    if os.name != "nt":
        return None, None
    import ctypes
    import uuid
    from ctypes import wintypes
    from orchestrator.process_ownership import kernel
    name = "Local\\AgenticSupervisor-" + uuid.uuid4().hex
    handle = kernel.CreateJobObjectW(None, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        kernel.CloseHandle(handle)
        raise ctypes.WinError(ctypes.get_last_error())
    # Deliberately retained for the process lifetime; unlike child Jobs, closing
    # this handle must not terminate the supervisor during normal Python exit.
    return name, handle


def control_dir(root: Path) -> Path:
    return root / "runtime/dispatch/layer_supervisor"


def read_control_status(path: Path, timeout: float = 3.0) -> dict:
    """Wait briefly for a readable root identity; callers still fence it normally.

    Heartbeat reads map malformed JSON and sharing violations to an empty dict.
    Never reuse a cached identity across reads or weaken process verification.
    """
    deadline = time.monotonic() + timeout
    while True:
        record = read_heartbeat(path)
        if (type(record.get("pid")) is int
                and isinstance(record.get("process_start_time"), str)
                and record["process_start_time"].strip()):
            return record
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return record
        time.sleep(min(.05, remaining))


@contextmanager
def file_lock(path: Path):
    """Nonblocking OS lock; a crash releases it without stale-lock recovery."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def identity_state(record: dict) -> str:
    """Distinguish absent, matching and reused/incomplete identities."""
    if not isinstance(record, dict):
        return "unknown"
    pid, expected = record.get("pid"), record.get("process_start_time")
    if (type(pid) is not int or not 0 < pid <= 0xffffffff
            or not isinstance(expected, str) or not expected.strip()):
        return "unknown"
    try:
        current = process_start_time(pid)
    except OSError:
        return "unknown"
    if current is not None:
        return "live" if current == expected else "reused"
    # An unreadable live process must never be treated as gone.
    if os.name == "nt":
        import ctypes
        from orchestrator.process_ownership import kernel
        ctypes.set_last_error(0)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return "gone" if ctypes.get_last_error() == 87 else "unknown"
        try:
            from ctypes import wintypes
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return "unknown"
            return "gone" if code.value != 259 else "unknown"
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "gone"
    except PermissionError:
        return "unknown"
    # Linux zombies cannot execute and are waiting for their parent's reap.
    if Path(f"/proc/{pid}/stat").exists():
        stat = Path(f"/proc/{pid}/stat").read_text()
        if stat[stat.rindex(")") + 2:].split()[0] == "Z":
            return "gone"
    return "unknown"


class StateRootMismatch(ValueError):
    """Recorded live process lacks evidence of ownership by the selected root."""


def recorded_state(record: dict, root: Path, entrypoints=("run_supervisor_layers.py",)) -> str:
    state = identity_state(record)
    if state != "live":
        return state
    try:
        import psutil
    except ImportError:
        return "unverified"
    try:
        process = psutil.Process(record["pid"])
        args = process.cmdline()
        if not any(Path(arg.replace("\\", "/")).name.casefold() in entrypoints for arg in args):
            return "foreign"
        selected = []
        for index, arg in enumerate(args):
            if arg == "--state-root":
                selected.append(args[index + 1] if index + 1 < len(args) else "")
            elif arg.startswith("--state-root="):
                selected.append(arg.split("=", 1)[1])
        if not selected:
            selected = [process.environ().get("AGENTIC_OS_STATE_ROOT", "")]
        for value in selected:
            if not value:
                return "unverified"
            path = Path(value)
            if not path.is_absolute():
                path = Path(process.cwd()) / path
            if str(path.resolve()).casefold() != str(root.resolve()).casefold():
                return "foreign"
        # Recheck creation identity after inspecting a reusable PID.
        return identity_state(record)
    except (OSError, ValueError, psutil.Error):
        return "unverified"


LAYER_ENTRYPOINTS = {"builder": "run_orchestrator.py", "claude": "run_claude_event_consumer.py"}


def verify_recorded_tree(record: dict, root: Path) -> None:
    records = [(record, ("run_supervisor_layers.py",))]
    children = record.get("children", {})
    history = record.get("recorded_children", [])
    if not isinstance(children, dict) or not isinstance(history, list):
        raise ValueError("invalid recorded child identities")
    for name, child in children.items():
        records.append((child, (LAYER_ENTRYPOINTS.get(name, ""),)))
    records.extend((child, tuple(LAYER_ENTRYPOINTS.values())) for child in history)
    for child, entries in records:
        if not isinstance(child, dict):
            raise ValueError("invalid recorded process identity")
        if child.get("pid") is None:
            continue
        state = recorded_state(child, root, entries)
        if state in {"foreign", "unverified"}:
            raise StateRootMismatch("recorded process belongs to another state root or ownership evidence is missing")
        if state == "unknown":
            raise ValueError("recorded process identity cannot be verified")


def force_recorded_tree(record: dict, root: Path) -> None:
    """Revalidate immediately before signaling; never select by executable name."""
    verify_recorded_tree(record, root)
    if os.name == "nt":
        from orchestrator.process_ownership import kernel, _windows_start_time
        # Retain the process object through Job membership and identity checks.
        handle = kernel.OpenProcess(0x1000, False, record["pid"])
        if not handle:
            raise OSError("cannot open recorded supervisor")
        try:
            if _windows_start_time(handle) != record["process_start_time"]:
                raise ValueError("root PID/start time changed; refusing termination")
            job_name = record.get("process_identity")
            if not isinstance(job_name, str) or not job_name.startswith("Local\\Agentic"):
                raise ValueError("root has no recorded tree Job; refusing termination")
            import ctypes
            from ctypes import wintypes
            kernel.OpenJobObjectW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
            kernel.OpenJobObjectW.restype = wintypes.HANDLE
            kernel.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
            kernel.IsProcessInJob.restype = wintypes.BOOL
            job = kernel.OpenJobObjectW(0x8 | 0x4, False, job_name)  # QUERY | TERMINATE
            if not job:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                member = wintypes.BOOL()
                if not kernel.IsProcessInJob(handle, job, ctypes.byref(member)) or not member.value:
                    raise ValueError("recorded root is not a member of recorded Job")
                if _windows_start_time(handle) != record["process_start_time"]:
                    raise ValueError("root identity changed immediately before termination")
                verify_recorded_tree(record, root)
                if not kernel.TerminateJobObject(job, 1):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                kernel.CloseHandle(job)
        finally:
            kernel.CloseHandle(handle)
    else:
        # POSIX supervisors must own their session/group, never the caller's.
        if os.getpgid(record["pid"]) != record["pid"] or identity_state(record) != "live":
            raise ValueError("root is not the recorded process-group owner")
        # owned_popen places each layer in a separate session. Fence each
        # recorded layer group independently, then revalidate the root again.
        for child in record.get("children", {}).values():
            child_pid = child.get("pid")
            if identity_state(child) in {"gone", "reused"}:
                continue
            if (identity_state(child) != "live"
                    or child.get("process_identity") != f"pgid:{child_pid}"
                    or os.getpgid(child_pid) != child_pid
                    or identity_state(record) != "live"):
                raise ValueError("cannot validate recorded layer group ownership")
            verify_recorded_tree(record, root)
            os.killpg(child_pid, signal.SIGKILL)
        if identity_state(record) != "live":
            raise ValueError("root identity changed immediately before termination")
        verify_recorded_tree(record, root)
        os.killpg(record["pid"], signal.SIGKILL)


ROOT_IDENTITY_FIELDS = frozenset({"pid", "process_start_time", "instance_token", "process_identity"})


def is_legacy_status(record: dict) -> bool:
    """Only records with no root identity fields qualify for explicit adoption."""
    return bool(record) and not ROOT_IDENTITY_FIELDS.intersection(record)


def legacy_process_blockers(root: Path) -> list[dict]:
    """Read-only process scan; unreadable candidate identities fail closed."""
    from orchestrator.process_inventory import legacy_process_inventory

    candidates = legacy_process_inventory()
    blockers = []
    for candidate in candidates:
        pid, args = candidate.pid, candidate.command_line
        cwd, environment_root = candidate.cwd, candidate.state_root_evidence
        options = {}
        for index, arg in enumerate(args):
            for flag in ("--state-root", "--root"):
                if arg == flag:
                    options[flag] = args[index + 1] if index + 1 < len(args) else ""
                elif arg.startswith(flag + "="):
                    options[flag] = arg.split("=", 1)[1]
        selected = options.get("--state-root") or environment_root or options.get("--root")
        resolved = None
        if selected:
            path = Path(selected)
            if path.is_absolute() or cwd is not None:
                resolved = (path if path.is_absolute() else cwd / path).resolve()
        # With no explicit root, cwd alone cannot exclude environment/default
        # script-root selection. Keep such candidates as uncertain blockers.
        if resolved is None or resolved == root.resolve():
            blockers.append({"pid": pid, "command": list(args), "cwd": str(cwd) if cwd else None,
                             "resolved_state_root": str(resolved) if resolved else None})
    return blockers
