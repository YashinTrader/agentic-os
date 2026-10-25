"""R12 stuck evidence replayed only in disposable state roots."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dispatch.atomic_io import atomic_write_json
from dispatch.assignment_channel import read_assignment
from dispatch.work_lock import lock_path
from orchestrator.stuck_assignments import recover_stuck_assignments
from scripts import assignments


class StuckAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        fixture = Path(__file__).parent / 'fixtures/r12_stuck'
        data = {p.stem: json.loads(p.read_text()) for p in fixture.glob('*.json')}
        self.aid = data['inbox']['assignment_id']
        self.rid = data['run_supervisor_run']['run_id']
        self.run_path = self.root / f'runtime/dispatch/runs/{self.rid}/supervisor_run.json'
        self.wake = self.root / f'runtime/dispatch/wake_queue/composer/{self.aid}.json'
        self.signal = data['dead_letter']
        for path, payload in [
            (self.root / f'runtime/dispatch/assignments/inbox/{self.aid}.json', data['inbox']),
            (self.root / f'runtime/dispatch/assignments/claims/{self.aid}.json', data['claim']),
            (lock_path(self.root, data['lock']['logical_task_id']), data['lock']),
            (self.run_path, data['run_supervisor_run']),
            (self.run_path.with_name('result.json'), data['run_result']),
            (self.root / f'runtime/dispatch/wake_queue/dead_letter/composer/{self.aid}.json', self.signal),
        ]:
            atomic_write_json(path, payload)

    def status(self):
        return read_assignment(self.root, self.aid)[0].status

    def notices(self):
        return list((self.root / 'runtime/dispatch/completion_notices').glob('*.json'))

    def cli(self):
        with patch.dict(os.environ, {}, clear=True), patch('sys.argv', [
            'assignments.py', '--root', str(self.root), 'fail', self.aid,
            '--actor', 'tester', '--note', 'review abandoned run']):
            return assignments.main()

    def test_sweep_once_and_idle_no_writes(self):
        self.assertEqual(recover_stuck_assignments(self.root), [self.aid])
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(recover_stuck_assignments(self.root), [])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(self.status(), 'reviewable_failure')
        self.assertEqual(len(self.notices()), 1)

    def test_active_and_launching_refused(self):
        for state in ['running', 'launching', 'queued']:
            payload = json.loads(self.run_path.read_text())
            payload['process_state'] = state
            atomic_write_json(self.run_path, payload)
            self.assertEqual(recover_stuck_assignments(self.root), [])
            self.assertEqual(self.cli(), 4)
            self.assertEqual(self.status(), 'building')
        self.assertEqual(self.notices(), [])

    def test_pending_wake_refused(self):
        atomic_write_json(self.wake, self.signal)
        self.assertEqual(recover_stuck_assignments(self.root), [])
        self.assertEqual(self.cli(), 4)
        self.assertEqual(self.status(), 'building')

    def test_operator_audit_and_idempotence(self):
        self.assertEqual(self.cli(), 0)
        self.assertEqual(self.cli(), 0)
        self.assertEqual(self.status(), 'reviewable_failure')
        audits = list((self.root / 'runtime/dispatch/assignments/failure_audit').glob('*.json'))
        self.assertEqual(len(audits), 1)
        audit = json.loads(audits[0].read_text())
        self.assertEqual(audit['actor'], 'tester')
        self.assertEqual(audit['note'], 'review abandoned run')
        self.assertIn(self.rid, audit['diagnostic'])
        self.assertEqual(len(self.notices()), 1)

    def test_builder_guard(self):
        with patch.dict(os.environ, {'AGENTIC_BUILDER_RUN_ID': 'fixture'}):
            self.assertEqual(assignments.main(), 3)
        self.assertEqual(self.status(), 'building')

    def test_absent_wake_config_failure_and_retryable_untouched(self):
        for path in (self.root / 'runtime/dispatch/wake_queue/dead_letter').rglob('*.json'):
            path.unlink()
        payload = json.loads(self.run_path.read_text())
        payload.update(process_state='failed_launch', retry_eligible=True, failure_class='TRANSIENT')
        atomic_write_json(self.run_path, payload)
        self.assertEqual(recover_stuck_assignments(self.root), [])
        payload.update(failure_class='CONFIG', retry_eligible=False)
        atomic_write_json(self.run_path, payload)
        self.assertEqual(recover_stuck_assignments(self.root), [self.aid])

    def test_exhausted_retries_and_claimed(self):
        inbox = self.root / f'runtime/dispatch/assignments/inbox/{self.aid}.json'
        payload = json.loads(inbox.read_text())
        payload['status'] = 'claimed'
        atomic_write_json(inbox, payload)
        payload = json.loads(self.run_path.read_text())
        payload.update(process_state='failed_launch', retry_eligible=True, failure_class='TRANSIENT')
        atomic_write_json(self.run_path, payload)
        self.assertEqual(recover_stuck_assignments(self.root), [self.aid])

    def test_other_active_run_is_not_hidden_by_terminal_owner(self):
        payload = json.loads(self.run_path.read_text())
        payload.update(run_id='other-active', process_state='launching')
        atomic_write_json(self.root / 'runtime/dispatch/runs/other-active/supervisor_run.json', payload)
        self.assertEqual(recover_stuck_assignments(self.root), [])
        self.assertEqual(self.cli(), 4)

    def test_builder_tick_calls_sweep(self):
        from orchestrator.supervisor import process_once
        with patch('orchestrator.supervisor.recover_orphans'), patch(
            'orchestrator.supervisor.reevaluate_blocked_builders', return_value=None):
            process_once(self.root)
            process_once(self.root)
        self.assertEqual(self.status(), 'reviewable_failure')
        self.assertEqual(len(self.notices()), 1)

    def test_launch_lease_without_run_refused(self):
        from orchestrator.leases import assignment_lease_path
        atomic_write_json(assignment_lease_path(self.root, self.aid), {'run_id': 'not-yet-persisted'})
        self.assertEqual(recover_stuck_assignments(self.root), [])
        self.assertEqual(self.cli(), 4)

    def test_absent_wake_exhausted_retry_budget(self):
        for path in (self.root / 'runtime/dispatch/wake_queue/dead_letter').rglob('*.json'):
            path.unlink()
        payload = json.loads(self.run_path.read_text())
        payload.update(process_state='failed', retry_eligible=True, retry_count=3)
        atomic_write_json(self.run_path, payload)
        self.assertEqual(recover_stuck_assignments(self.root, max_automatic_retry=4), [])
        self.assertEqual(recover_stuck_assignments(self.root, max_automatic_retry=3), [self.aid])
