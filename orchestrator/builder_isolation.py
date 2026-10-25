"""Fail-closed Windows builder boundary. No external dependencies or elevation.

MIC denies writes to Medium objects. Other Low locations remain writable.
Job ownership is lifecycle control only; workspace labels are temporary.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os
import re
from pathlib import Path
import subprocess
import time
import uuid


class IsolationError(OSError):
    pass


def standalone_workspace(root: Path) -> Path:
    if getattr(root.lstat(), 'st_file_attributes', 0) & 0x400:
        raise IsolationError('workspace root is a reparse point')
    root = root.resolve(strict=True)
    if not (root / '.git').is_dir():
        raise IsolationError('builder requires standalone clone with its own .git directory')
    if (root / '.git/commondir').exists() or (root / '.git/objects/info/alternates').exists():
        raise IsolationError('shared Git metadata/objects are forbidden')
    # Never label through junctions, symlinks, or other reparse points.
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            if getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
                raise IsolationError(f'reparse point in workspace: {path}')
            if path.is_file() and path.stat().st_nlink > 1:
                raise IsolationError(f'hardlinked file in workspace: {path}')
    return root


def builder_environment(root: Path, profile: Path, run_id: str) -> dict[str, str]:
    # Allowlist: do not inherit credentials, Git redirections, Python injection,
    # live roots, CLI config redirections, or arbitrary supervisor environment.
    allowed = {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'PATHEXT', 'SYSTEMDRIVE'}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    for key in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP',
                'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME', 'GROK_HOME'):
        env[key] = str(profile)
    env.update(AGENTIC_BUILDER_RUN_ID=run_id, AGENTIC_BUILDER_WORKTREE=str(root),
               PYTHONDONTWRITEBYTECODE='1')
    return env


def _label(root: Path, level='low'):
    result = subprocess.run(['icacls.exe', str(root), '/setintegritylevel',
                             f'(OI)(CI){level}', '/T', '/Q'],
                            capture_output=True, text=True, timeout=120, check=False)
    if result.returncode:
        raise IsolationError(f'workspace labelling failed ({result.returncode}): '
                             f'{result.stdout} {result.stderr}')


def _has_low_label(sddl):
    for sid in re.findall(r'\(ML;[^)]*;;;([^;)]+)\)', sddl):
        if sid in {'LW', 'UN'} or (sid.startswith('S-1-16-') and int(sid[7:]) < 8192):
            return True
    return False


def _is_low(path):
    descriptor, sacl, rendered = C.c_void_p(), C.c_void_p(), W.LPWSTR()
    try:
        status = adv.GetNamedSecurityInfoW(str(path), 1, 0x10, None, None,
                                          None, C.byref(sacl), C.byref(descriptor))
        if status:
            raise IsolationError(f'integrity inspection ({status}): {path}')
        _check(adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, 1, 0x10, C.byref(rendered), None), 'render integrity')
        return _has_low_label(rendered.value or '')
    finally:
        if rendered:
            kernel.LocalFree(C.cast(rendered, C.c_void_p))
        if descriptor:
            kernel.LocalFree(descriptor)


def assert_medium_tree(root: Path):
    """Inspect mandatory labels without relying on localized icacls output."""
    def inspect(path):
        if getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
            raise IsolationError(f'reparse point in builder inventory: {path}')
        if _is_low(path):
            raise IsolationError(f'stale Low workspace label: {path}')
    inspect(root)
    def error(exc):
        raise IsolationError(f'inventory traversal failed: {exc}') from exc
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=error):
        for name in dirs + files:
            inspect(Path(directory) / name)


def _check_workspaces(root, inventory):
    if not root.is_relative_to(inventory) or root == inventory:
        raise IsolationError('workspace outside builder inventory')
    # Inspect the entire configured inventory, not just the current task folder.
    assert_medium_tree(inventory)


if os.name == 'nt':
    adv = C.WinDLL('advapi32', use_last_error=True)
    kernel = C.WinDLL('kernel32', use_last_error=True)
    class SIDATTR(C.Structure):
        _fields_ = [('sid', C.c_void_p), ('attributes', W.DWORD)]
    class SI(C.Structure):
        _fields_ = [('cb', W.DWORD), ('reserved', W.LPWSTR), ('desktop', W.LPWSTR),
                   ('title', W.LPWSTR), ('x', W.DWORD), ('y', W.DWORD),
                   ('xs', W.DWORD), ('ys', W.DWORD), ('xc', W.DWORD), ('yc', W.DWORD),
                   ('fill', W.DWORD), ('flags', W.DWORD), ('show', W.WORD),
                   ('reserved2size', W.WORD), ('reserved2', C.c_void_p),
                   ('stdin', W.HANDLE), ('stdout', W.HANDLE), ('stderr', W.HANDLE)]
    class SIX(C.Structure):
        _fields_ = [('si', SI), ('attributes', C.c_void_p)]
    class PI(C.Structure):
        _fields_ = [('process', W.HANDLE), ('thread', W.HANDLE),
                   ('pid', W.DWORD), ('tid', W.DWORD)]
    signatures = [
        (adv, 'GetNamedSecurityInfoW', [W.LPCWSTR, C.c_int, W.DWORD,
          C.c_void_p, C.c_void_p, C.c_void_p, C.POINTER(C.c_void_p), C.POINTER(C.c_void_p)], W.DWORD),
        (adv, 'ConvertSecurityDescriptorToStringSecurityDescriptorW',
          [C.c_void_p, W.DWORD, W.DWORD, C.POINTER(W.LPWSTR), C.c_void_p], W.BOOL),
        (adv, 'OpenProcessToken', [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)], W.BOOL),
        (adv, 'CreateRestrictedToken', [W.HANDLE, W.DWORD, W.DWORD, C.c_void_p,
          W.DWORD, C.c_void_p, W.DWORD, C.POINTER(SIDATTR), C.POINTER(W.HANDLE)], W.BOOL),
        (adv, 'ConvertStringSidToSidW', [W.LPCWSTR, C.POINTER(C.c_void_p)], W.BOOL),
        (adv, 'SetTokenInformation', [W.HANDLE, C.c_int, C.c_void_p, W.DWORD], W.BOOL),
        (adv, 'CreateProcessAsUserW', [W.HANDLE, W.LPCWSTR, W.LPWSTR, C.c_void_p,
          C.c_void_p, W.BOOL, W.DWORD, C.c_void_p, W.LPCWSTR, C.POINTER(SIX), C.POINTER(PI)], W.BOOL),
        (kernel, 'CreateMutexW', [C.c_void_p, W.BOOL, W.LPCWSTR], W.HANDLE),
        (kernel, 'ReleaseMutex', [W.HANDLE], W.BOOL),
        (kernel, 'QueryInformationJobObject', [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.c_void_p], W.BOOL),
        (kernel, 'GetCurrentProcess', [], W.HANDLE),
        (kernel, 'CloseHandle', [W.HANDLE], W.BOOL),
        (kernel, 'LocalFree', [C.c_void_p], C.c_void_p),
        (kernel, 'ResumeThread', [W.HANDLE], W.DWORD),
        (kernel, 'TerminateProcess', [W.HANDLE, W.UINT], W.BOOL),
        (kernel, 'WaitForSingleObject', [W.HANDLE, W.DWORD], W.DWORD),
        (kernel, 'GetExitCodeProcess', [W.HANDLE, C.POINTER(W.DWORD)], W.BOOL),
    ]
    for dll, name, args, result in signatures:
        fn = getattr(dll, name)
        fn.argtypes, fn.restype = args, result


def _check(ok, operation):
    if not ok:
        raise IsolationError(f'{operation}: {C.WinError(C.get_last_error())}')


def _acquire_builder_gate():
    handle = kernel.CreateMutexW(None, False, 'Global\\AgenticOS-LowBuilder-v1')
    _check(handle, 'builder gate')
    if C.get_last_error() == 183:  # includes reentrant launches on the same thread
        kernel.CloseHandle(handle)
        raise IsolationError('another builder is active')
    if kernel.WaitForSingleObject(handle, 0) not in (0, 0x80):
        kernel.CloseHandle(handle)
        raise IsolationError('another builder is active')
    return handle


def _wait_tree(job):
    # JOBOBJECT_BASIC_ACCOUNTING_INFORMATION: four LARGE_INTEGERs + four DWORDs.
    accounting = C.create_string_buffer(48)
    deadline = time.monotonic() + 30
    while True:
        _check(kernel.QueryInformationJobObject(job, 1, accounting, 48, None), 'query tree')
        if W.DWORD.from_buffer(accounting, 40).value == 0:
            return
        if time.monotonic() > deadline:
            raise IsolationError('builder tree did not exit')
        time.sleep(.01)


class IsolatedProcess:
    """Small Popen-compatible process with a retained kill-on-close job."""
    def __init__(self, info, owner, root, mutex):
        self.pid, self._handle, self._agentic_owner = info.pid, info.process, owner
        self.returncode = None
        self._root, self._mutex = root, mutex

    def poll(self):
        if kernel.WaitForSingleObject(self._handle, 0) == 0:
            code = W.DWORD()
            _check(kernel.GetExitCodeProcess(self._handle, C.byref(code)), 'exit code')
            # Root exit is not tree exit. Kill remaining descendants, then wait
            # for the job to empty before restoring labels or exposing results.
            if self._mutex:
                from orchestrator.process_ownership import kernel as owner_kernel
                _check(owner_kernel.TerminateJobObject(self._agentic_owner.job, 1), 'stop descendants')
                _wait_tree(self._agentic_owner.job)
                _label(self._root, 'medium')
                assert_medium_tree(self._root)
                self._agentic_owner.close()
                _check(kernel.ReleaseMutex(self._mutex), 'release builder gate')
                kernel.CloseHandle(self._mutex)
                self._mutex = None
            self.returncode = code.value
        return self.returncode

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(str(self.pid), timeout)
            time.sleep(.01)
        return self.returncode

    def terminate(self):
        if self._agentic_owner.job:
            from orchestrator.process_ownership import kernel as owner_kernel
            _check(owner_kernel.TerminateJobObject(self._agentic_owner.job, 1), 'terminate tree')
        self.wait(30)

    kill = terminate

    def drain_output(self):
        for thread in getattr(self, '_relay_threads', ()):
            thread.join(timeout=5)

    def __del__(self):
        if getattr(self, '_handle', None):
            kernel.CloseHandle(self._handle)
            self._handle = None


def isolated_popen(argv, *, cwd, env=None, stdout=None, stderr=None, stdin=None,
                   shell=False, text=True, **kwargs):
    """No fallback to unrestricted execution, including on unsupported systems.

    Only pipe stdio may be inherited. Callers must not hand writable supervisor
    files to a restricted child (inherited handles bypass filesystem checks).
    """
    if os.name != 'nt':
        raise IsolationError('Windows restricted-token boundary unavailable')
    if shell or kwargs:
        raise IsolationError('unsupported isolated process options')
    root = standalone_workspace(Path(cwd))
    profile = root / '.agentic/profile'
    profile.mkdir(parents=True, exist_ok=True)
    inventory = Path((env or {}).get('AGENTIC_BUILDER_INVENTORY_ROOT', str(root.parent))).resolve()
    mutex = _acquire_builder_gate()
    labelled = False
    low = C.c_void_p()
    original, token = W.HANDLE(), W.HANDLE()
    info = PI()
    job = None
    duplicates = []
    attributes = None
    try:
        _check_workspaces(root, inventory)
        _check(adv.ConvertStringSidToSidW('S-1-16-4096', C.byref(low)), 'Low SID')
        _check(adv.OpenProcessToken(kernel.GetCurrentProcess(), 0xF01FF, C.byref(original)), 'open token')
        _check(adv.CreateRestrictedToken(original, 0x1, 0, None, 0, None,
                                         0, None, C.byref(token)), 'restrict token')
        label = SIDATTR(low, 0x20)
        _check(adv.SetTokenInformation(token, 25, C.byref(label), C.sizeof(label) + 12), 'lower integrity')
        labelled = True  # partial labelling failures also require restoration
        _label(root)
        import msvcrt
        si = SIX()
        si.si.cb = C.sizeof(si)
        si.si.flags = 0x100  # STARTF_USESTDHANDLES
        handles = []
        for stream, field in ((stdin, 'stdin'), (stdout, 'stdout'), (stderr, 'stderr')):
            if stream is None:
                raise IsolationError('isolated stdio must be explicit pipes')
            raw = msvcrt.get_osfhandle(stream.fileno())
            kernel.GetFileType.argtypes, kernel.GetFileType.restype = [W.HANDLE], W.DWORD
            if kernel.GetFileType(raw) != 3:  # FILE_TYPE_PIPE
                raise IsolationError('isolated stdio must be pipes, never inherited file handles')
            dup = os.dup(stream.fileno())
            os.set_inheritable(dup, True)
            duplicates.append(dup)
            handle = msvcrt.get_osfhandle(dup)
            handles.append(handle)
            setattr(si.si, field, handle)
        kernel.InitializeProcThreadAttributeList.argtypes = [C.c_void_p, W.DWORD, W.DWORD, C.POINTER(C.c_size_t)]
        kernel.UpdateProcThreadAttribute.argtypes = [C.c_void_p, W.DWORD, C.c_size_t, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p]
        kernel.DeleteProcThreadAttributeList.argtypes = [C.c_void_p]
        size = C.c_size_t()
        kernel.InitializeProcThreadAttributeList(None, 1, 0, C.byref(size))
        attributes = C.create_string_buffer(size.value)
        _check(kernel.InitializeProcThreadAttributeList(attributes, 1, 0, C.byref(size)), 'stdio attributes')
        handle_list = (W.HANDLE * 3)(*handles)
        _check(kernel.UpdateProcThreadAttribute(attributes, 0, 0x20002, handle_list,
                                               C.sizeof(handle_list), None, None), 'stdio handle list')
        si.attributes = C.cast(attributes, C.c_void_p)
        environment = builder_environment(root, profile, (env or {}).get('AGENTIC_BUILDER_RUN_ID', uuid.uuid4().hex))
        block = C.create_unicode_buffer('\0'.join(f'{k}={v}' for k, v in sorted(environment.items())) + '\0\0')
        command = C.create_unicode_buffer(subprocess.list2cmdline([str(a) for a in argv]))
        from orchestrator.process_ownership import kernel as owner_kernel, ExtendedLimits, ProcessOwner, process_start_time
        job = owner_kernel.CreateJobObjectW(None, None)
        _check(job, 'create job')
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000
        _check(owner_kernel.SetInformationJobObject(job, 9, C.byref(limits), C.sizeof(limits)), 'job limits')
        _check(adv.CreateProcessAsUserW(token, None, command, None, None, True,
                                       0x4 | 0x400 | 0x80000 | 0x08000000,
                                       block, str(root), C.byref(si), C.byref(info)), 'create isolated process')
        _check(owner_kernel.AssignProcessToJobObject(job, info.process), 'own isolated process')
        start = process_start_time(info.pid)
        if not start:
            raise IsolationError('cannot identify isolated process')
        _check(kernel.ResumeThread(info.thread) != 0xFFFFFFFF, 'resume isolated process')
        owner = ProcessOwner(info.pid, start, 'isolated:' + uuid.uuid4().hex, job)
        proc = IsolatedProcess(info, owner, root, mutex)
        mutex = None
        job = None
        info.process = None
        return proc
    finally:
        if info.process:
            kernel.TerminateProcess(info.process, 1)
            _check(kernel.WaitForSingleObject(info.process, 30000) == 0, 'failed launch exit')
            kernel.CloseHandle(info.process)
        if info.thread:
            kernel.CloseHandle(info.thread)
        if job:
            kernel.CloseHandle(job)
        if attributes:
            kernel.DeleteProcThreadAttributeList(attributes)
        for fd in duplicates:
            os.close(fd)
        for handle in (token, original):
            if handle:
                kernel.CloseHandle(handle)
        if mutex:
            if labelled:
                _label(root, 'medium')
                assert_medium_tree(root)
            kernel.ReleaseMutex(mutex)
            kernel.CloseHandle(mutex)
        for pointer in (low,):
            if pointer:
                kernel.LocalFree(pointer)


def launch_isolated(argv, *, cwd, stdout, stderr, stdin=None, env=None):
    """Supervisor-side pipe relay; child inherits no file or token handles."""
    import threading
    pipes = [os.pipe() for _ in range(3)]
    child = [os.fdopen(pipes[0][0], 'rb', buffering=0),
             os.fdopen(pipes[1][1], 'wb', buffering=0),
             os.fdopen(pipes[2][1], 'wb', buffering=0)]
    parent = [os.fdopen(pipes[0][1], 'wb', buffering=0),
              os.fdopen(pipes[1][0], 'rb', buffering=0),
              os.fdopen(pipes[2][0], 'rb', buffering=0)]
    try:
        proc = isolated_popen(argv, cwd=cwd, env=env, stdin=child[0], stdout=child[1], stderr=child[2])
    except BaseException:
        for stream in parent:
            stream.close()
        raise
    finally:
        for stream in child:
            stream.close()
    def relay(source, target):
        try:
            while chunk := source.read(4096):
                target.write(chunk.decode('utf-8', errors='replace'))
                target.flush()
        finally:
            source.close()
            target.close()
    # Duplicate destinations so callers may close their copies after launch.
    proc._relay_threads = []
    for source, target in zip(parent[1:], (stdout, stderr)):
        destination = os.fdopen(os.dup(target.fileno()), 'w', encoding='utf-8')
        thread = threading.Thread(target=relay, args=(source, destination), daemon=True)
        proc._relay_threads.append(thread)
        thread.start()
    def feed():
        try:
            if stdin is not None:
                parent[0].write(stdin.read().encode('utf-8'))
        except BrokenPipeError:
            pass
        finally:
            parent[0].close()
    # Capture text now: launch_process closes its stdin file on return.
    if stdin is not None:
        import io
        stdin = io.StringIO(stdin.read())
    threading.Thread(target=feed, daemon=True).start()
    return proc
