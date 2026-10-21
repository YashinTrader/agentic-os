"""Serialize completion with ownership transfer and retain rejected evidence."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict, is_dataclass
from functools import wraps
import inspect
import json
import uuid

from dispatch import work_lock
from dispatch.atomic_io import atomic_create_json

_active = ContextVar("completion_transaction", default=None)


def _authorized(root, logical_id, assignment_id, run_id):
    record = work_lock._read(work_lock.lock_path(root, logical_id))
    if record:
        return (record['assignment_id'] == assignment_id and
                ((bool(run_id) and record['run_id'] == run_id) or
                 (not run_id and record['state'] == 'reserved' and not record['run_id'])))
    # Only a release by this same run permits a post-release result. The newest
    # ownership event must be that release; an older release cannot revive a run.
    events = []
    for path in (work_lock.lock_dir(root) / 'audit').glob('*.json'):
        event = json.loads(path.read_text(encoding='utf-8'))
        if event['prior_holder']['logical_task_id'] == logical_id:
            events.append(event)
    latest = max(events, key=lambda event: event['recorded_at'], default=None)
    return bool(run_id and latest and latest['action'] == 'release' and
                latest['prior_holder']['run_id'] == run_id and
                latest['prior_holder']['assignment_id'] == assignment_id)


def fenced_completion(fn):
    """Guard the entire outcome transaction, including status changes and pokes."""
    signature = inspect.signature(fn)

    @wraps(fn)
    def wrapped(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        values = bound.arguments
        root = values['repo_root']
        state = values.get('state')
        assignment_id = state.assignment_id if state else values['assignment_id']
        run_id = state.run_id if state else values.get('run_id')
        from dispatch.assignment_channel import read_assignment
        assignment, _ = read_assignment(root, assignment_id)
        logical_id = ((assignment.logical_task_id or assignment.task_id) if assignment else
                      (state.logical_task_id or state.task_id) if state else values.get('task_id', assignment_id))
        key = (str(root.resolve()), logical_id, assignment_id, run_id)
        if _active.get() == key:
            return fn(*args, **kwargs)
        with work_lock._guard(work_lock.lock_path(root, logical_id)):
            if not _authorized(root, logical_id, assignment_id, run_id):
                evidence = {k: asdict(v) if is_dataclass(v) else str(v)
                            for k, v in values.items() if k != 'repo_root'}
                atomic_create_json(root / 'runtime/dispatch/fenced' / f'{uuid.uuid4().hex}.json',
                                   dict(status='fenced', assignment_id=assignment_id,
                                        run_id=run_id, logical_task_id=logical_id,
                                        recorded_at=work_lock.now(), evidence=evidence))
                result = dict(assignment_id=assignment_id, run_id=run_id,
                              process_state='fenced', outbox_status=None, poke=None)
                return (result if state else None), ['fenced: work lock ownership changed']
            token = _active.set(key)
            try:
                return fn(*args, **kwargs)
            finally:
                _active.reset(token)
    return wrapped
