"""Recover abandoned terminal builds without launching or inspecting processes."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from dispatch.assignment_channel import list_inbox_assignments, read_assignment
from dispatch.atomic_io import atomic_write_json
from orchestrator.runtime_store import TERMINAL_STATES, list_supervisor_runs, utc_now
from orchestrator.leases import assignment_lease_path
from dispatch.work_lock import WorkLockError


class RecoveryRefused(ValueError):
    """The assignment still has pending or active work."""


def pending_work(root: Path, assignment_id: str, states) -> bool:
    if assignment_lease_path(root, assignment_id).exists():
        return True
    if any(s.process_state not in TERMINAL_STATES for s in states):
        return True
    queue = root / 'runtime/dispatch/wake_queue'
    for path in queue.glob('*/*.json'):
        if path.parent.name == 'dead_letter':
            continue
        # Invalid pending evidence is not permission to end work.
        try:
            if json.loads(path.read_text(encoding='utf-8')).get('assignment_id') == assignment_id:
                return True
        except (OSError, ValueError):
            return True
    return False


def fail_assignment(root: Path, assignment_id: str, *, actor: str, note: str,
                    automatic: bool = False, max_automatic_retry: int = 1, states=None) -> bool:
    """Use the existing fenced failure policy; retain ownership for review."""
    from orchestrator.supervisor import _exhaust_assignment
    record, errors = read_assignment(root, assignment_id)
    if record is None:
        raise ValueError('; '.join(errors) or 'assignment not found')
    if record.status == 'reviewable_failure':
        return False
    if record.status not in {'building', 'claimed'}:
        raise ValueError('fail requires building or claimed')
    if not actor.strip() or not note.strip():
        raise ValueError('actor and note must be nonempty')
    states = [s for s in (list_supervisor_runs(root, limit=None) if states is None else states)
              if s.assignment_id == assignment_id]
    if pending_work(root, assignment_id, states):
        raise RecoveryRefused('active/launching run or pending wake; no changes made')
    latest = states[0] if states else None
    exhausted = bool(latest and latest.failure_fingerprint and not latest.blocked_on and
                     latest.retry_count >= max_automatic_retry)
    for path in (root / 'runtime/dispatch/wake_queue/dead_letter').rglob('*.json'):
        try:
            wake = json.loads(path.read_text(encoding='utf-8'))
            exhausted |= (wake.get('assignment_id') == assignment_id and
                          int(wake.get('retry', {}).get('attempts', 0)) >= 3)
        except (OSError, ValueError, TypeError):
            continue
    if automatic and (latest is None or latest.process_state == 'completed' or
                      (latest.retry_eligible and latest.process_state != 'max_turns' and
                       latest.failure_class not in {'CONFIG', 'BLOCKED_SECURITY_POLICY'} and not exhausted)):
        return False
    diagnostic = '; '.join(
        f'run_id={s.run_id} state={s.process_state} failure_class={s.failure_class or s.process_state} '
        f'retry_eligible={s.retry_eligible} token_usage={s.token_usage} '
        f'turn_limit={_turn_limit(s.command_redacted)} '
        f'turns_used={_turn_limit(s.command_redacted) if s.process_state == "max_turns" else "unknown"} '
        f'reason={s.blocked_reason}' for s in states)
    reason = f'{actor}: {note}; {diagnostic}'
    audit = root / 'runtime/dispatch/assignments/failure_audit' / f'{uuid.uuid4().hex}.json'
    atomic_write_json(audit, dict(assignment_id=assignment_id, actor=actor, note=note,
                                recorded_at=utc_now(), previous_status=record.status,
                                action='fail', automatic=automatic, diagnostic=diagnostic))
    try:
        _exhaust_assignment(root, assignment_id, reason)
    except WorkLockError as exc:
        raise RecoveryRefused(str(exc)) from exc
    updated, _ = read_assignment(root, assignment_id)
    if updated.status != 'reviewable_failure':
        raise RecoveryRefused('ownership fence refused failure; inspect audit and current holder')
    return True


def _turn_limit(command):
    try:
        return command[command.index('--max-turns') + 1]
    except (ValueError, IndexError):
        return 'unknown'


def recover_stuck_assignments(root: Path, *, max_automatic_retry: int = 1, states=None) -> list[str]:
    """Read-only on idle ticks; durable status makes repeat sweeps no-ops."""
    records, _ = list_inbox_assignments(root)
    recovered = []
    states = list_supervisor_runs(root, limit=None) if states is None else states
    for record in records:
        if record.status not in {'building', 'claimed'}:
            continue
        try:
            if fail_assignment(root, record.assignment_id, actor='supervisor',
                               note='terminal run without pending wake; reviewer recovery', automatic=True,
                               max_automatic_retry=max_automatic_retry, states=states):
                recovered.append(record.assignment_id)
        except RecoveryRefused:
            continue
    return recovered
