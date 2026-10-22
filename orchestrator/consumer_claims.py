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


def process_liveness(pid, start) -> bool | None:
    """False means OS-confirmed absence, exit or PID reuse; access errors are unknown."""
    if (not isinstance(pid, int) or isinstance(pid, bool) or not 0 < pid <= 0xffffffff
            or not isinstance(start, str) or not start.strip()):
        return None
    try:
        actual = process_start_time(pid)
    except OSError:
        return None
    if actual is not None:
        return actual == str(start)
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


def claim_liveness(record: dict) -> tuple[bool | None, bool | None]:
    return (process_liveness(record.get('consumer_pid'), record.get('consumer_start_time')),
            process_liveness(record.get('review_pid'), record.get('review_start_time')))


def audit(root: Path, event: str, prior: dict, *, actor: str, reason: str) -> dict:
    if not actor.strip() or not reason.strip():
        raise ValueError('actor and reason must be non-empty')
    record = dict(event=event, actor=actor, reason=reason, prior_owner=prior,
                  at=datetime.now(timezone.utc).isoformat())
    path = directory(root) / 'audit' / f'{uuid.uuid4().hex}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_create_json(path, record)
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
            if not prior.get('consumer_token') or claim_liveness(prior) != (False, False):
                return False, None
            recovered = audit(root, 'claim_recovered', prior, actor='consumer',
                              reason='consumer and review child identities are provably dead')
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


def stale_claims(root: Path, now: datetime) -> list[dict]:
    result = []
    for path in sorted((directory(root) / 'claims').glob('*.json')):
        try:
            prior = read_record(path)
        except (OSError, ValueError):
            prior = {}
        if prior.get('consumer_token') and prior.get('consumer_pid') and prior.get('consumer_start_time'):
            continue
        try:
            age = max(0, int((now - datetime.fromisoformat(prior['claimed_at'].replace('Z', '+00:00'))).total_seconds()))
        except (KeyError, TypeError, ValueError):
            age = None
        result.append(dict(fingerprint=path.stem, assignment_id=prior.get('assignment_id'),
                           age_seconds=age, reason='legacy or unreadable owner identity'))
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
        evidence.append((prior.get('review_pid'), prior.get('review_start_time')))
    run = prior.get('review_run_id')
    if run:
        if not isinstance(run, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', run):
            raise ValueError('invalid review run identity')
        path = root / 'runtime/dispatch/reviews' / run / 'review_run.json'
        if path.exists():
            state = read_record(path)
            if state.get('pid'):
                evidence.append((state['pid'], state.get('process_start_time')))
    return evidence


def _owner_evidence(prior: dict) -> list[tuple]:
    result = []
    if 'consumer_pid' in prior or prior.get('consumer_token'):
        result.append((prior.get('consumer_pid'), prior.get('consumer_start_time')))
    if 'pid' in prior:
        result.append((prior.get('pid'), prior.get('process_start_time')))
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
        evidence = _review_evidence(root, prior) + _owner_evidence(prior)
        if kind == 'claim' and aid:
            lease = _target(root, f'review-{aid}', 'lease')
            if lease.exists():
                lease_record = read_record(lease)
                evidence.extend(_review_evidence(root, lease_record) + _owner_evidence(lease_record))
        if any(process_liveness(pid, start) is not False for pid, start in evidence):
            raise ValueError('live or unknown process owns this record')
        record = audit(root, f'{kind}_released', prior, actor=actor, reason=reason)
        path.unlink()
        return record


def list_records(root: Path) -> dict:
    return {kind: [dict(key=p.stem, **read_record(p)) for p in sorted(folder.glob(pattern))]
            for kind, folder, pattern in (
                ('claims', directory(root) / 'claims', '*.json'),
                ('leases', root / 'runtime/dispatch/supervisor_leases', 'review-*.json'))}
