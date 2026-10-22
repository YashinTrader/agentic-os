"""Fenced claim mutations and explicit, durable recovery audits.

Unknown process identity/liveness never authorizes automatic recovery.
The short OS guard is shared with the consumer and review lease writer.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import uuid
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from dispatch.atomic_io import atomic_create_json, atomic_write_json
from dispatch.work_lock import _guard, WorkLockError
from orchestrator.process_ownership import process_start_time


def directory(root: Path) -> Path:
    return root / 'runtime/dispatch/claude_event_consumer'


@contextmanager
def mutation_guard(root: Path):
    deadline = time.monotonic() + 2.5
    while True:
        guard = _guard(directory(root) / 'mutation.json')
        try:
            guard.__enter__()
            break
        except WorkLockError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.025)
    try:
        yield
    finally:
        guard.__exit__(None, None, None)


def read_record(path: Path) -> dict:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'invalid record: {path.name}')
    return value


def process_liveness(pid, start, recorded_at=None) -> bool | None:
    """False means OS-confirmed absence, exit or PID reuse; access errors are unknown."""
    if (not isinstance(pid, int) or isinstance(pid, bool) or not 0 < pid <= 0xffffffff
            or (start is not None and (not isinstance(start, str) or not start.strip()))):
        return None
    try:
        actual = process_start_time(pid)
    except OSError:
        return None
    if actual is not None:
        if start is not None:
            return actual == str(start)
        return legacy_creation_liveness(actual, recorded_at)
    if os.name == 'nt':
        from orchestrator.process_ownership import kernel
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False if ctypes.get_last_error() == 87 else None
        try:
            code = ctypes.c_ulong()
            if kernel.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value != 259:
                return False
            return None
        finally:
            kernel.CloseHandle(handle)
    # /proc distinguishes zombies from permission failures without signaling a PID.
    import sys
    if sys.platform == 'linux':
        try:
            stat = Path(f'/proc/{pid}/stat').read_text()
            return False if stat[stat.rindex(')') + 2:].split()[0] == 'Z' else None
        except FileNotFoundError:
            return False
        except (OSError, ValueError, IndexError):
            return None
    return None


def legacy_creation_liveness(actual, recorded_at) -> bool | None:
    """Only creation after this PID-holding record proves legacy PID reuse."""
    try:
        recorded = datetime.fromisoformat(recorded_at.replace('Z', '+00:00'))
        if recorded.tzinfo is None:
            return None
        if os.name == 'nt':
            created = (int(actual) - 116444736000000000) / 10000000
        else:
            ticks = os.sysconf('SC_CLK_TCK')
            boot = next(line.split()[1] for line in Path('/proc/stat').read_text().splitlines()
                        if line.startswith('btime '))
            created = int(boot) + int(actual) / ticks
        return False if created > recorded.timestamp() else None
    except (AttributeError, TypeError, ValueError, OSError, StopIteration, OverflowError):
        return None


def record_start(record: dict):
    return next((record[k] for k in ('started_at', 'claimed_at', 'acquired_at') if record.get(k)), None)


def evidence_liveness(pid, start, recorded_at):
    # Keep the established identity path shared by automatic recovery and release.
    return process_liveness(pid, start) if start is not None else process_liveness(pid, start, recorded_at)


def claim_liveness(record: dict) -> tuple[bool | None, bool | None]:
    return (process_liveness(record.get('consumer_pid'), record.get('consumer_start_time')),
            process_liveness(record.get('review_pid'), record.get('review_start_time')))


def recovery_reason(root: Path, prior: dict) -> str | None:
    """Shared automatic recovery fence; callers must hold mutation_guard."""
    if (not prior.get('consumer_token') or not prior.get('consumer_start_time') or
            process_liveness(prior.get('consumer_pid'), prior.get('consumer_start_time')) is not False):
        return None
    try:
        children = [(pid, start, recorded_at) for pid, start, recorded_at in _review_evidence(root, prior) if pid is not None]
    except (OSError, ValueError, TypeError):
        return None  # Unreadable run evidence cannot prove that its child died.
    if any(not start or process_liveness(pid, start) is not False for pid, start, recorded_at in children):
        return None
    # owned_popen's consumer-owned KILL_ON_JOB_CLOSE job prevents an
    # unrecorded review child from surviving a provably dead consumer.
    return ('consumer and review child identities are provably dead' if children else
            'consumer identity is provably dead; no review child recorded')


def recover_review_leases(root: Path) -> list[dict]:
    with mutation_guard(root):
        return recover_review_leases_locked(root)


def recover_review_leases_locked(root: Path) -> list[dict]:
    """Recover before counting capacity, in the same mutation transaction."""
    recovered = []
    for path in sorted((root / 'runtime/dispatch/supervisor_leases').glob('review-*.json')):
        try:
            prior = read_record(path)
        except (OSError, ValueError):
            continue
        reason = recovery_reason(root, prior)
        if reason:
            recovered.append(audit(root, 'lease_recovered', prior, actor='consumer', reason=reason))
            path.unlink()
    return recovered


def stale_review_leases(root: Path, now: datetime) -> list[dict]:
    result = []
    for path in sorted((root / 'runtime/dispatch/supervisor_leases').glob('review-*.json')):
        try:
            prior = read_record(path)
        except (OSError, ValueError):
            prior = {}
        alive = process_liveness(prior.get('consumer_pid'), prior.get('consumer_start_time'))
        if prior.get('consumer_token') and alive is True:
            continue
        reason = ('legacy or unreadable owner identity' if not prior.get('consumer_token') else
                  'consumer liveness is unknown' if alive is None else
                  'consumer identity is provably dead; review child recovery is fenced')
        try:
            age = max(0, int((now - datetime.fromisoformat(prior['acquired_at'].replace('Z', '+00:00'))).total_seconds()))
        except (KeyError, TypeError, ValueError):
            age = None
        result.append(dict(key=path.stem, assignment_id=prior.get('assignment_id') or path.stem.removeprefix('review-'),
                           age_seconds=age, reason=reason))
    return result


def audit(root: Path, event: str, prior: dict, *, actor: str, reason: str,
          reference_paths: list[Path] | None = None) -> dict:
    if not actor.strip() or not reason.strip():
        raise ValueError('actor and reason must be non-empty')
    record = dict(event=event, actor=actor, reason=reason, prior_owner=prior,
                  at=datetime.now(timezone.utc).isoformat())
    path = directory(root) / 'audit' / f'{uuid.uuid4().hex}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_create_json(path, record)
    if reference_paths is not None:
        reference_paths.append(path)
    return record


def acquire(root: Path, fingerprint: str, payload: dict) -> tuple[bool, dict | None]:
    """Recover and acquire in one transaction; all contenders observe the new owner."""
    path = directory(root) / 'claims' / f'{fingerprint}.json'
    recovered = None
    with mutation_guard(root):
        if (directory(root) / 'resolved' / f'{fingerprint}.json').exists():
            return False, None
        if path.exists():
            prior = read_record(path)
            reason = recovery_reason(root, prior)
            if not reason:
                return False, None
            recovered = audit(root, 'claim_recovered', prior, actor='consumer', reason=reason)
            path.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_create_json(path, payload)
    return True, recovered


def update_child(root: Path, fingerprint: str, token: str, pid, start) -> None:
    with mutation_guard(root):
        path = directory(root) / 'claims' / f'{fingerprint}.json'
        record = read_record(path)
        if record.get('consumer_token') != token:
            raise ValueError('consumer claim ownership changed')
        if start is None and record.get('review_pid') == pid:
            start = record.get('review_start_time')
        record.update(review_pid=pid, review_start_time=start)
        atomic_write_json(path, record)


def finish(root: Path, fingerprint: str, token: str) -> None:
    with mutation_guard(root):
        path = directory(root) / 'claims' / f'{fingerprint}.json'
        if path.exists() and read_record(path).get('consumer_token') == token:
            path.unlink()


def stale_claims(root: Path, now: datetime, *, consumer_token: str | None = None) -> list[dict]:
    result = []
    for path in sorted((directory(root) / 'claims').glob('*.json')):
        try:
            prior = read_record(path)
        except (OSError, ValueError):
            prior = {}
        reason = 'legacy or unreadable owner identity'
        if prior.get('consumer_token'):
            if prior['consumer_token'] == consumer_token:
                continue
            alive = process_liveness(prior.get('consumer_pid'), prior.get('consumer_start_time'))
            if alive is True:
                continue
            reason = 'consumer liveness is unknown' if alive is None else 'consumer identity is provably dead'
        try:
            age = max(0, int((now - datetime.fromisoformat(prior['claimed_at'].replace('Z', '+00:00'))).total_seconds()))
        except (KeyError, TypeError, ValueError):
            age = None
        result.append(dict(fingerprint=path.stem, assignment_id=prior.get('assignment_id'),
                           age_seconds=age, reason=reason))
    return result


def _target(root: Path, key: str, kind: str) -> Path:
    if kind == 'claim':
        if not re.fullmatch('[0-9a-f]{64}', key):
            raise ValueError('fingerprint must be 64 lowercase hex characters')
        return directory(root) / 'claims' / f'{key}.json'
    if kind != 'lease' or not re.fullmatch(r'review-[A-Za-z0-9_-]+', key):
        raise ValueError('lease key must be a review-<assignment> basename without .json')
    return root / 'runtime/dispatch/supervisor_leases' / f'{key}.json'


def _review_evidence(root: Path, prior: dict) -> list[tuple]:
    evidence = []
    if 'review_pid' in prior:
        evidence.append((prior.get('review_pid'), prior.get('review_start_time'), record_start(prior)))
    run = prior.get('review_run_id')
    if run:
        if not isinstance(run, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', run):
            raise ValueError('invalid review run identity')
        path = root / 'runtime/dispatch/reviews' / run / 'review_run.json'
        if path.exists():
            state = read_record(path)
            if state.get('pid') is not None:
                evidence.append((state['pid'], state.get('process_start_time'), record_start(state)))
    return evidence


def _owner_evidence(prior: dict) -> list[tuple]:
    result = []
    if 'consumer_pid' in prior or prior.get('consumer_token'):
        result.append((prior.get('consumer_pid'), prior.get('consumer_start_time'), record_start(prior)))
    if 'pid' in prior:
        result.append((prior.get('pid'), prior.get('process_start_time'), record_start(prior)))
    return result


def release(root: Path, key: str, *, actor: str, reason: str, kind: str = 'claim') -> dict:
    """Manual legacy recovery is intentional; recorded unknown identities still fence it."""
    if not actor.strip() or not reason.strip():
        raise ValueError('actor and reason must be non-empty')
    path = _target(root, key, kind)
    with mutation_guard(root):
        prior = read_record(path)
        resolved = directory(root) / 'resolved'
        if kind == 'claim' and (resolved / f'{key}.json').exists():
            raise ValueError('resolved record exists')
        aid = prior.get('assignment_id') or (key.removeprefix('review-') if kind == 'lease' else None)
        for item in resolved.glob('*.json'):
            if aid and read_record(item).get('assignment_id') == aid:
                raise ValueError('resolved record exists for assignment')
        owners = [prior]
        evidence = _review_evidence(root, prior) + _owner_evidence(prior)
        if kind == 'claim' and aid:
            lease = _target(root, f'review-{aid}', 'lease')
            if lease.exists():
                lease_record = read_record(lease)
                owners.append(lease_record)
                evidence.extend(_review_evidence(root, lease_record) + _owner_evidence(lease_record))
        if any(evidence_liveness(pid, start, recorded_at) is not False for pid, start, recorded_at in evidence if pid is not None):
            raise ValueError('live or unknown process owns this record')
        audit_paths = []
        record = audit(root, f'{kind}_released', prior, actor=actor, reason=reason,
                       reference_paths=audit_paths)
        for owner in owners:
            run = owner.get('review_run_id')
            if not run:
                continue
            state_path = root / 'runtime/dispatch/reviews' / run / 'review_run.json'
            if not state_path.exists():
                continue
            original = state_path.read_bytes()
            state = json.loads(original)
            if state.get('process_state') in ('running', 'queued'):
                snapshot = state_path.with_name('review_run.before_abandonment.json')
                if not snapshot.exists():
                    from dispatch.atomic_io import atomic_write_text
                    atomic_write_text(snapshot, original.decode('utf-8'))
                state.update(process_state='abandoned', completed_at=record['at'],
                             blocked_reason=reason, recovery_audits=[
                                 {'path': p.relative_to(root).as_posix(), **record} for p in audit_paths])
                atomic_write_json(state_path, state)
        path.unlink()
        return record


def list_records(root: Path) -> dict:
    result = {}
    for kind, folder, pattern in (
            ('claims', directory(root) / 'claims', '*.json'),
            ('leases', root / 'runtime/dispatch/supervisor_leases', 'review-*.json')):
        records = []
        for path in sorted(folder.glob(pattern)):
            try:
                prior = read_record(path)
            except (OSError, ValueError) as exc:
                prior = {'error': str(exc)}
            records.append({**prior, 'key': path.stem})
        result[kind] = records
    return result
