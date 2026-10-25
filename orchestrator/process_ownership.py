"""Own process trees, never select processes by executable name.

Windows children start suspended, enter a kill-on-close Job, then resume.
A live Job handle remains the authority even after its root process exits.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import sys
import subprocess
import uuid

_Popen = subprocess.Popen

if os.name == "nt":
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    for name, args, result in (
        ("CreateJobObjectW", [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        ("OpenProcess", [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        ("CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
        ("AssignProcessToJobObject", [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        ("TerminateJobObject", [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        ("SetInformationJobObject", [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        ("GetProcessTimes", [wintypes.HANDLE] + [ctypes.c_void_p] * 4, wintypes.BOOL),
        ("GetExitCodeProcess", [wintypes.HANDLE, ctypes.c_void_p], wintypes.BOOL),
    ):
        fn = getattr(kernel, name)
        fn.argtypes, fn.restype = args, result

    class BasicLimits(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                    ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t),
                    ("max_ws", ctypes.c_size_t), ("active", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                    ("scheduling", wintypes.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", BasicLimits), ("io", ctypes.c_uint64 * 6),
                    ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                    ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]


def process_start_time(pid: int) -> str | None:
    """OS creation identity; absent/inaccessible processes have no identity."""
    if pid <= 0:
        return None
    if os.name == "nt":
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            return _windows_start_time(handle)
        finally:
            kernel.CloseHandle(handle)
    if sys.platform != "linux":
        result = subprocess.run(["ps", "-p", str(pid), "-o", "lstart=", "-o", "stat="],
                                capture_output=True, text=True, check=False)
        value = result.stdout.strip()
        return value if result.returncode == 0 and value and "Z" not in value.split()[-1] else None
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        fields = stat[stat.rindex(")") + 2:].split()
        return None if fields[0] == "Z" else fields[19]
    except (OSError, ValueError, IndexError):
        return None


def _windows_start_time(handle) -> str | None:
    times = [ctypes.c_uint64() for _ in range(4)]
    code = wintypes.DWORD()
    if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
        return None
    if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
        return None
    return str(times[0].value)


def pid_is_alive(pid: int, expected_start_time: str | None = None) -> bool | None:
    # Historical bare PIDs are deliberately not trusted during recovery.
    if not expected_start_time:
        return None
    current = process_start_time(pid)
    if current is not None:
        return current == expected_start_time
    if os.name == "nt":
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False if ctypes.get_last_error() == 87 else None
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return None
            return False if code.value != 259 else None
        finally:
            kernel.CloseHandle(handle)
    return False


@dataclass
class ProcessOwner:
    pid: int
    process_start_time: str
    process_identity: str
    job: int | None = None

    def metadata(self):
        return {"process_start_time": self.process_start_time,
                "process_identity": self.process_identity}

    def close(self):
        if self.job:
            kernel.CloseHandle(self.job)
            self.job = None

    def __del__(self):
        self.close()


def owned_popen(argv, *, popen=None, **kwargs):
    """Injection remains available for fake processes; real Popen always owns a tree."""
    runner = popen or subprocess.Popen
    job = None
    identity = "group"
    if os.name == "nt":
        identity = "Local\\AgenticRun-" + uuid.uuid4().hex
        job = kernel.CreateJobObjectW(None, identity)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            kernel.CloseHandle(job)
            raise ctypes.WinError(ctypes.get_last_error())
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x4  # CREATE_SUSPENDED
    else:
        kwargs["start_new_session"] = True
    proc = None
    try:
        proc = runner(argv, **kwargs)
        if not isinstance(proc, _Popen):
            # Injected test doubles do not represent OS children.
            if job:
                kernel.CloseHandle(job)
            return proc
        if job and not kernel.AssignProcessToJobObject(job, int(proc._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        start = process_start_time(proc.pid)
        if not start:
            raise OSError("cannot establish process creation identity")
        proc._agentic_owner = ProcessOwner(proc.pid, start, identity if job else f"pgid:{proc.pid}", job)
        if job:
            resume = ctypes.WinDLL("ntdll").NtResumeProcess
            resume.argtypes, resume.restype = [wintypes.HANDLE], ctypes.c_long
            if resume(int(proc._handle)) != 0:
                raise OSError("cannot resume owned child")
        return proc
    except BaseException:
        # This is the child just created, using Popen's retained handle on Windows.
        if proc is not None:
            proc.kill()
            proc.wait(timeout=5)
        if job:
            kernel.CloseHandle(job)
            if proc is not None and hasattr(proc, "_agentic_owner"):
                proc._agentic_owner.job = None
        raise


def ownership_metadata(process) -> dict:
    owner = getattr(process, "_agentic_owner", None)
    return owner.metadata() if isinstance(owner, ProcessOwner) else {}


def terminate_owned(process) -> bool:
    from orchestrator.builder_isolation import IsolatedProcess
    if isinstance(process, IsolatedProcess) and process._mutex:
        process.terminate()
        return True
    owner = getattr(process, "_agentic_owner", None)
    if not isinstance(owner, ProcessOwner):
        # No OS signaling for unowned PIDs. Test doubles can expose kill().
        if not isinstance(process, _Popen) and process.poll() is None:
            process.kill()
        return False
    current = process_start_time(owner.pid)
    if current is not None and current != owner.process_start_time:
        return False
    if owner.job:
        # Job handle identifies the original tree without consulting a reusable PID.
        if not kernel.TerminateJobObject(owner.job, 1):
            raise ctypes.WinError(ctypes.get_last_error())
        owner.close()
        return True
    if not pid_is_alive(owner.pid, owner.process_start_time):
        return False
    try:
        os.killpg(owner.pid, signal.SIGKILL)
    except ProcessLookupError:
        return False
    return True


def owned_run(argv, *, timeout: float, cwd=None, env=None, capture_output=True,
              text=True, check=False, shell=False):
    """Bound a short helper and its descendants without inherited pipe waits."""
    import tempfile
    from orchestrator.layer_heartbeat import wait_with_heartbeat

    if shell or not capture_output or not text:
        raise ValueError("owned_run requires text capture and shell=False")
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        proc = owned_popen(argv, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL,
                           shell=False, cwd=cwd, env=env)
        try:
            wait_with_heartbeat(proc, timeout)
        finally:
            terminate_owned(proc)
            proc.wait(timeout=2)
        stdout.seek(0)
        stderr.seek(0)
        result = subprocess.CompletedProcess(argv, proc.returncode,
                    stdout.read().decode("utf-8", errors="replace"),
                    stderr.read().decode("utf-8", errors="replace"))
        if check:
            result.check_returncode()
        return result
