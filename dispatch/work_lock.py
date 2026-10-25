"""Cross-route logical work ownership. Never infer permission from lock age."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid
import threading

from dispatch.atomic_io import atomic_create_json, atomic_write_json

TERMINAL_STATES = frozenset({"accepted", "rejected", "superseded", "cancelled"})
STALE_SECONDS = 900


class WorkLockError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def lock_dir(root: Path) -> Path:
    return root / "runtime" / "dispatch" / "locks"


def lock_path(root: Path, logical_task_id: str) -> Path:
    if not isinstance(logical_task_id, str) or not logical_task_id.strip():
        raise WorkLockError("logical_task_id must be non-empty")
    return lock_dir(root) / (hashlib.sha256(logical_task_id.encode()).hexdigest() + ".json")


@contextmanager
def _guard(path: Path):
    """Serialize mutations with an OS lock, released even after process death.

    This is only a short transaction guard. Durable work ownership never expires.
    Keep its inode in place so waiters cannot lock different files for one task.
    """
    guard = path.with_suffix(".guard")
    guard.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(guard, os.O_CREAT | os.O_RDWR)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        raise WorkLockError(f"work lock mutation busy: {path.stem}; retry (never steal)") from exc
    try:
        yield
    finally:
        os.close(fd)


def _read(path: Path) -> dict | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        required = {'logical_task_id', 'holder_agent', 'route', 'assignment_id',
                    'run_id', 'base_sha', 'branch', 'acquired_at', 'heartbeat_at', 'state'}
        if not isinstance(record, dict) or not required.issubset(record):
            raise ValueError('invalid work lock record')
        timestamp = datetime.fromisoformat(record['heartbeat_at'].replace('Z', '+00:00'))
        if timestamp.tzinfo is None:
            raise ValueError('heartbeat_at must include timezone')
        return record
    except FileNotFoundError:
        return None
    except (ValueError, OSError) as exc:
        raise WorkLockError(f"unreadable work lock {path}: {exc}") from exc


def _conflict(record: dict) -> WorkLockError:
    return WorkLockError(
        f"logical task {record['logical_task_id']} held by {record['holder_agent']} "
        f"via {record['route']} ({record['assignment_id'] or record['run_id']}); "
        "explicit release or supersede required"
    )


def acquire(root: Path, logical_task_id: str, *, holder_agent: str, route: str,
            assignment_id: str = "", run_id: str = "", base_sha: str = "",
            branch: str = "", resume: bool = False) -> dict:
    path = lock_path(root, logical_task_id)
    if not holder_agent or not route or not (assignment_id or run_id):
        raise WorkLockError("holder_agent, route and assignment_id or run_id are required")
    with _guard(path):
        prior = _read(path)
        if prior:
            same_assignment = bool(assignment_id and prior['assignment_id'] == assignment_id)
            same_run = bool(run_id and prior['run_id'] == run_id)
            if (resume and same_assignment and prior['holder_agent'] == holder_agent
                    and prior['state'] not in {'reserved', 'running', 'queued', 'launching'}):
                # Upgrade terminal locks written before reservation-on-completion.
                # Durable run evidence, never age, authorizes this transition.
                from orchestrator.runtime_store import load_run_state, TERMINAL_STATES as RUN_TERMINAL
                ended = load_run_state(root, prior['run_id'])
                if (ended and ended.assignment_id == assignment_id
                        and ended.assigned_agent == holder_agent
                        and ended.process_state in RUN_TERMINAL and ended.retry_eligible):
                    _reserve(prior)
            if (resume and prior['holder_agent'] == holder_agent
                    and (same_assignment if assignment_id else same_run)
                    and (not run_id or prior['state'] == 'reserved' or same_run)):
                prior.update(heartbeat_at=now())
                if run_id:
                    if prior['run_id'] and prior['run_id'] != run_id:
                        history = prior.setdefault('prior_run_ids', [])
                        if prior['run_id'] not in history:
                            history.append(prior['run_id'])
                    prior.update(run_id=run_id, route=route, state="running",
                                 base_sha=base_sha or prior['base_sha'], branch=branch or prior['branch'])
                atomic_write_json(path, prior)
                return prior
            raise _conflict(prior)
        stamp = now()
        record = dict(logical_task_id=logical_task_id, holder_agent=holder_agent,
                      route=route, assignment_id=assignment_id, run_id=run_id,
                      base_sha=base_sha, branch=branch, acquired_at=stamp,
                      heartbeat_at=stamp, state="running" if run_id else "reserved")
        atomic_create_json(path, record)
        return record


def status(root: Path, logical_task_id: str | None = None, *, stale_seconds: int = STALE_SECONDS) -> list[dict]:
    paths = [lock_path(root, logical_task_id)] if logical_task_id else sorted(lock_dir(root).glob("*.json"))
    records = []
    for path in paths:
        record = _read(path)
        if record:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(record['heartbeat_at'].replace('Z', '+00:00'))).total_seconds()
            stale = age > stale_seconds or bool(record.get('stale_reason'))
            records.append({**record, "stale": stale,
                            "lock_status": "stale" if stale else record['state']})
    return records


def report_ghost(root: Path, logical_task_id: str, *, run_id: str) -> dict:
    """Mark missing/terminal-run evidence without releasing or changing ownership."""
    path = lock_path(root, logical_task_id)
    with _guard(path):
        record = _read(path)
        if not record or record['run_id'] != run_id:
            raise WorkLockError('work lock run ownership changed')
        record.update(stale_reason='ghost_holder')
        atomic_write_json(path, record)
        return record


def _audit(root: Path, prior: dict, *, actor: str, reason: str, action: str) -> None:
    if not actor.strip() or not reason.strip():
        raise WorkLockError("actor and reason must be non-empty")
    atomic_create_json(lock_dir(root) / "audit" / f"{uuid.uuid4().hex}.json",
                       dict(action=action, actor=actor, reason=reason, recorded_at=now(), prior_holder=prior))


def release(root: Path, logical_task_id: str, *, actor: str, reason: str,
            assignment_id: str = "", run_id: str = "") -> None:
    path = lock_path(root, logical_task_id)
    with _guard(path):
        prior = _read(path)
        if not prior:
            return
        if ((assignment_id and prior['assignment_id'] != assignment_id)
                or (run_id and prior['run_id'] != run_id)):
            raise _conflict(prior)
        _audit(root, prior, actor=actor, reason=reason, action="release")
        path.unlink()


def supersede(root: Path, logical_task_id: str, *, actor: str, reason: str,
              holder_agent: str, route: str, assignment_id: str = "", run_id: str = "",
              base_sha: str = "", branch: str = "", expected_assignment_id: str = "", expected_run_id: str = "") -> dict:
    if not holder_agent or not route or not (assignment_id or run_id):
        raise WorkLockError("replacement holder, route and assignment_id or run_id required")
    path = lock_path(root, logical_task_id)
    with _guard(path):
        prior = _read(path)
        if not prior:
            raise WorkLockError("no holder to supersede")
        if ((expected_assignment_id and prior['assignment_id'] != expected_assignment_id)
                or (expected_run_id and prior['run_id'] != expected_run_id)):
            raise _conflict(prior)
        _audit(root, prior, actor=actor, reason=reason, action="supersede")
        stamp = now()
        replacement = dict(logical_task_id=logical_task_id, holder_agent=holder_agent,
                           route=route, assignment_id=assignment_id, run_id=run_id,
                           base_sha=base_sha, branch=branch, acquired_at=stamp,
                           heartbeat_at=stamp, state="running" if run_id else "reserved")
        atomic_write_json(path, replacement)
        return replacement


def heartbeat(root: Path, logical_task_id: str, *, run_id: str, state: str | None = None, branch: str | None = None,
              reserve: bool = False) -> None:
    path = lock_path(root, logical_task_id)
    with _guard(path):
        record = _read(path)
        if not record or record['run_id'] != run_id:
            raise WorkLockError("work lock run ownership changed")
        if state in TERMINAL_STATES:
            _audit(root, record, actor=record['holder_agent'], reason=state, action='release')
            path.unlink()
            return
        record['heartbeat_at'] = now()
        if branch:
            record['branch'] = branch
        if state:
            record['state'] = state
        if reserve:
            _reserve(record)
        atomic_write_json(path, record)


def _reserve(record: dict) -> None:
    """Caller holds _guard; retain the last physical owner for completion fencing."""
    history = record.setdefault('prior_run_ids', [])
    if record['run_id'] and record['run_id'] not in history:
        history.append(record['run_id'])
    if record['state'] != 'reserved':
        record['last_run_state'] = record['state']
    record['state'] = 'reserved'


def concurrency_error(root: Path, maximum: int) -> str:
    if maximum <= 1:
        return ""
    from dispatch.execution_policy import load_execution_policy
    try:
        enabled = load_execution_policy(root).get("work_lock_enabled") is True
    except (OSError, ValueError):
        enabled = False
    return "" if enabled else "builder concurrency above 1 requires work_lock_enabled: true"


@contextmanager
def keepalive(root: Path, logical_task_id: str, run_id: str, *, interval: float = 30):
    """Heartbeat while a blocking subprocess is owned; stop when the call returns."""
    stop = threading.Event()
    errors = []

    def refresh():
        while not stop.wait(interval):
            try:
                heartbeat(root, logical_task_id, run_id=run_id)
            except (WorkLockError, OSError) as exc:
                errors.append(exc)
                return

    thread = threading.Thread(target=refresh, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
    if errors:
        raise errors[0]


def logical_id_for_task(root: Path, task: dict, *, seen: frozenset[str] = frozenset()) -> str:
    """Explicit ids split work; parent_task_id follows YAML ancestry otherwise."""
    if task.get('logical_task_id'):
        return str(task['logical_task_id'])
    task_id = str(task.get('id') or '')
    if not task_id or task_id in seen:
        raise WorkLockError('missing task id or cyclic parent_task_id')
    if task.get('parent_assignment_id'):
        from dispatch.assignment_channel import read_assignment
        parent, errors = read_assignment(root, str(task['parent_assignment_id']))
        if parent is None:
            raise WorkLockError('; '.join(errors))
        return parent.logical_task_id or parent.task_id
    parent_id = task.get('parent_task_id')
    if not parent_id:
        # An explicit logical id supplied on assignment creation need not have
        # rewritten the YAML. Direct builders must still respect that contract.
        identities = set()
        for path in (root / 'runtime/dispatch/assignments/inbox').glob('*.json'):
            try:
                assignment = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError) as exc:
                raise WorkLockError(f'unreadable assignment identity {path}: {exc}') from exc
            if (isinstance(assignment, dict) and assignment.get('task_id') == task_id
                    and assignment.get('status') not in TERMINAL_STATES):
                identities.add(str(assignment.get('logical_task_id') or task_id))
        if len(identities) > 1:
            raise WorkLockError(f'ambiguous logical identity for {task_id}; set logical_task_id explicitly')
        if identities:
            return identities.pop()
        return task_id
    import yaml
    for directory in ('active', 'done', 'blocked'):
        for path in sorted((root / 'tasks' / directory).glob('*.yaml')):
            parent = yaml.safe_load(path.read_text(encoding='utf-8'))
            if isinstance(parent, dict) and parent.get('id') == parent_id:
                return logical_id_for_task(root, parent, seen=seen | {task_id})
    raise WorkLockError(f'parent task {parent_id} not found; refusing independent dispatch')
