"""Read-only snapshots for legacy adoption refusal; never process ownership authority."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessRecord:
    pid: int
    start_time: float
    command_line: tuple[str, ...]
    cwd: Path
    state_root_evidence: str | None


def legacy_process_inventory() -> tuple[ProcessRecord, ...]:
    """Snapshot runtime candidates, refusing unreadable identities conservatively."""
    try:
        import psutil
    except ImportError as exc:
        raise ValueError("legacy adoption requires psutil for process inspection") from exc
    scripts = {"run_supervisor_layers.py", "run_orchestrator.py", "run_claude_event_consumer.py"}
    candidates = []
    for process in psutil.process_iter(["pid", "name"]):
        try:
            args = process.cmdline()
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            if "python" in (process.info.get("name") or "").lower():
                raise ValueError(f"cannot inspect Python process {process.pid}")
            continue
        if not any(Path(arg.replace("\\", "/")).name.lower() in scripts for arg in args):
            continue
        try:
            start_time = process.create_time()
            cwd = Path(process.cwd()).resolve()
            environment_root = process.environ().get("AGENTIC_OS_STATE_ROOT")
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as exc:
            raise ValueError(f"cannot inspect runtime process {process.pid}: {args}") from exc
        candidates.append(ProcessRecord(process.pid, start_time, tuple(args), cwd, environment_root))
    return tuple(candidates)
