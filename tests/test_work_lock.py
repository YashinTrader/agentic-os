"""Global work ownership across assignment, worker, supervisor and manual routes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import yaml
from dispatch import work_lock as locks
from dispatch.assignment_channel import (
    write_assignment, claim_assignment, complete_assignment, accept_assignment,
    reject_assignment, set_assignment_status, read_assignment, create_assignment_from_task_yaml,
)

ROOT = Path(__file__).resolve().parents[1]


class WorkLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def acquire(self, logical='T-1', **kwargs):
        return locks.acquire(self.root, logical, holder_agent='codex', route='manual', run_id='run-1', **kwargs)

    def assignment(self, **kwargs):
        path, errors = write_assignment(self.root, task_id=kwargs.pop('task_id', 'T-1'), **kwargs)
        self.assertEqual(errors, [])
        self.assertIsNotNone(path)
        return path.stem

    def test_duplicate_create_and_legacy_claim_name_holder(self):
        aid = self.assignment()
        path, errors = write_assignment(self.root, task_id='T-1', assigned_to='codex')
        self.assertIsNone(path)
        self.assertIn('composer', ' '.join(errors))
        self.assertIn(aid, ' '.join(errors))
        # A legacy inbox file may exist without a work reservation.
        original = self.root / 'runtime/dispatch/assignments/inbox' / f'{aid}.json'
        payload = json.loads(original.read_text())
        payload.update(assignment_id='legacy', assigned_to='codex', adapter_id='codex-restricted', execution_route='codex_local_builder')
        original.with_name('legacy.json').write_text(json.dumps(payload))
        record, errors = claim_assignment(self.root, 'legacy', claimed_by='codex', sync_task_yaml=False)
        self.assertIsNone(record)
        self.assertIn(aid, ' '.join(errors))
        self.assertIn('composer', ' '.join(errors))

    def test_correction_inherits_and_blocks_then_proceeds_after_accept(self):
        parent = self.assignment(logical_task_id='family')
        path, errors = write_assignment(self.root, task_id='T-1B', parent_assignment_id=parent)
        self.assertIsNone(path)
        self.assertIn('family', ' '.join(errors))
        claim_assignment(self.root, parent, sync_task_yaml=False)
        complete_assignment(self.root, parent, sync_task_yaml=False)
        accept_assignment(self.root, parent, sync_task_yaml=False)
        child = self.assignment(task_id='T-1B', parent_assignment_id=parent)
        self.assertEqual(read_assignment(self.root, child)[0].logical_task_id, 'family')

    def test_yaml_followups_inherit_parent_task_and_explicit_split(self):
        directory = self.root / 'tasks/active'
        directory.mkdir(parents=True)
        (directory / 'parent.yaml').write_text(yaml.safe_dump({'id': 'T-1', 'logical_task_id': 'family'}))
        child = directory / 'child.yaml'
        child.write_text(yaml.safe_dump({'id': 'T-1B', 'parent_task_id': 'T-1'}))
        self.assignment(logical_task_id='family')
        path, errors = create_assignment_from_task_yaml(self.root, child)
        self.assertIsNone(path)
        self.assertIn('family', ' '.join(errors))
        path, errors = create_assignment_from_task_yaml(self.root, child, logical_task_id='split')
        self.assertEqual(errors, [])
        self.assertEqual(read_assignment(self.root, path.stem)[0].logical_task_id, 'split')

    def test_different_logical_tasks_independent(self):
        self.acquire('T-1')
        self.acquire('T-2')
        self.assertEqual(len(locks.status(self.root)), 2)

    def test_atomic_race_exactly_one_winner(self):
        barrier = threading.Barrier(12)
        def compete(index):
            barrier.wait()
            try:
                locks.acquire(self.root, 'race', holder_agent=f'agent-{index}', route='race', run_id=str(index))
                return True
            except locks.WorkLockError:
                return False
        with ThreadPoolExecutor(max_workers=12) as pool:
            outcomes = list(pool.map(compete, range(12)))
        self.assertEqual(sum(outcomes), 1)
        self.assertEqual(len(locks.status(self.root)), 1)

    def test_terminal_states_release_and_claim_does_not_reacquire(self):
        for terminal in ('accepted', 'rejected', 'superseded'):
            with self.subTest(terminal=terminal):
                aid = self.assignment(task_id=terminal)
                claim_assignment(self.root, aid, sync_task_yaml=False)
                complete_assignment(self.root, aid, sync_task_yaml=False)
                if terminal == 'accepted':
                    record, errors = accept_assignment(self.root, aid, sync_task_yaml=False)
                elif terminal == 'rejected':
                    record, errors = reject_assignment(self.root, aid, note='reject', sync_task_yaml=False)
                else:
                    record, errors = set_assignment_status(self.root, aid, terminal, sync_task_yaml=False)
                self.assertEqual(errors, [])
                self.assertEqual(locks.status(self.root, terminal), [])
                self.assertIsNone(claim_assignment(self.root, aid, sync_task_yaml=False)[0])
                self.assertEqual(locks.status(self.root, terminal), [])

    def test_failure_and_timeout_keep_holder(self):
        self.acquire()
        for state in ('failed', 'timed_out'):
            locks.heartbeat(self.root, 'T-1', run_id='run-1', state=state)
            self.assertEqual(locks.status(self.root)[0]['state'], state)
            with self.assertRaisesRegex(locks.WorkLockError, 'codex'):
                locks.acquire(self.root, 'T-1', holder_agent='composer', route='assignment', assignment_id='other')

    def test_stale_no_steal_and_supersede_audits_prior(self):
        record = self.acquire()
        record['heartbeat_at'] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        locks.lock_path(self.root, 'T-1').write_text(json.dumps(record))
        self.assertTrue(locks.status(self.root)[0]['stale'])
        with self.assertRaises(locks.WorkLockError):
            self.acquire()
        replacement = locks.supersede(self.root, 'T-1', actor='claude', reason='operator inspected stopped run',
                                      holder_agent='composer', route='supervisor', assignment_id='next')
        self.assertEqual(replacement['holder_agent'], 'composer')
        audit = json.loads(next((locks.lock_dir(self.root) / 'audit').glob('*.json')).read_text())
        self.assertEqual(audit['prior_holder'], record)
        self.assertEqual(audit['actor'], 'claude')
        self.assertTrue(audit['reason'])

    def test_dashboard_existing_errors_field_reports_stale(self):
        from dashboard.app import load_composer_assignment_index
        self.assignment()
        record = locks.status(self.root)[0]
        record['heartbeat_at'] = '2000-01-01T00:00:00+00:00'
        locks.lock_path(self.root, 'T-1').write_text(json.dumps(record))
        index, errors = load_composer_assignment_index(self.root)
        self.assertIn('stale', ' '.join(index['by_task_id']['T-1']['errors']))
        self.assertTrue(read_assignment(self.root, record['assignment_id'])[0].work_lock_status['stale'])

    def test_manual_cli_round_trip(self):
        def cli(*args):
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/work_lock.py'), '--root', str(self.root), *args], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        cli('acquire', 'cli', '--holder-agent', 'codex', '--run-id', 'manual-1', '--base-sha', 'abc', '--branch', 'agent/test')
        self.assertEqual(cli('status', 'cli')[0]['run_id'], 'manual-1')
        cli('supersede', 'cli', '--actor', 'claude', '--reason', 'stopped', '--holder-agent', 'composer', '--assignment-id', 'a2')
        self.assertEqual(cli('status', 'cli')[0]['assignment_id'], 'a2')
        cli('release', 'cli', '--actor', 'claude', '--reason', 'done')
        self.assertEqual(cli('status', 'cli'), [])

    def test_concurrency_guard_policy_and_supervisor(self):
        from dispatch.execution_policy import validate_execution_policy
        from orchestrator.leases import try_acquire_concurrency
        self.assertIn('work_lock_enabled', locks.concurrency_error(self.root, 2))
        self.assertIn('work_lock_enabled', try_acquire_concurrency(self.root, assignment_id='a', run_id='r', holder='x', max_concurrency=2)[1])
        policy = yaml.safe_load((ROOT / 'config/execution-policy.yaml').read_text())
        policy.update(maximum_concurrent_runs=2, work_lock_enabled=False)
        self.assertTrue(any('work_lock_enabled' in error for error in validate_execution_policy(policy)))
        (self.root / 'config').mkdir()
        policy['work_lock_enabled'] = True
        (self.root / 'config/execution-policy.yaml').write_text(yaml.safe_dump(policy))
        self.assertEqual(locks.concurrency_error(self.root, 2), '')

    def test_worker_blocks_assignment_holder_before_builder(self):
        spec = importlib.util.spec_from_file_location('worker', ROOT / 'scripts/run_local_builder_worker.py')
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        aid = self.assignment()
        task = self.root / 'task.yaml'
        task.write_text('id: T-1\n')
        with patch.object(worker, 'load_execution_policy', return_value={'maximum_concurrent_runs': 1}), patch.object(worker, 'run_local_builder') as builder:
            report = worker.process_one(self.root, task_path=task)
        self.assertEqual(report['status'], 'skipped')
        self.assertIn(aid, report['reason'])
        builder.assert_not_called()

    def test_launch_reservation_can_be_adopted_only_once(self):
        aid = self.assignment()
        locks.acquire(self.root, 'T-1', holder_agent='composer', route='supervisor', assignment_id=aid, run_id='first', resume=True)
        with self.assertRaisesRegex(locks.WorkLockError, 'composer'):
            locks.acquire(self.root, 'T-1', holder_agent='composer', route='supervisor', assignment_id=aid, run_id='second', resume=True)

    def test_old_assignment_cannot_release_or_supersede_new_holder(self):
        aid = self.assignment()
        locks.supersede(self.root, 'T-1', actor='claude', reason='replacement', holder_agent='codex', route='manual', run_id='next')
        with self.assertRaises(locks.WorkLockError):
            locks.release(self.root, 'T-1', actor='claude', reason='old accepted', assignment_id=aid)
        with self.assertRaises(locks.WorkLockError):
            locks.supersede(self.root, 'T-1', actor='claude', reason='old reassignment', holder_agent='composer', route='supervisor', assignment_id='wrong', expected_assignment_id=aid)
        self.assertEqual(locks.status(self.root)[0]['run_id'], 'next')

    def test_keepalive_refreshes_and_stops(self):
        self.acquire()
        refreshed = threading.Event()
        actual = locks.heartbeat
        def heartbeat(*args, **kwargs):
            actual(*args, **kwargs)
            refreshed.set()
        with patch.object(locks, 'heartbeat', side_effect=heartbeat):
            with locks.keepalive(self.root, 'T-1', 'run-1', interval=0.01):
                self.assertTrue(refreshed.wait(2))

    def test_worker_adopts_assigned_codex_reservation_and_failure_retains(self):
        from types import SimpleNamespace
        spec = importlib.util.spec_from_file_location('worker', ROOT / 'scripts/run_local_builder_worker.py')
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        aid = self.assignment(assigned_to='codex')
        task = self.root / 'task.yaml'
        task.write_text('id: T-1\n')
        def result(*args, **kwargs):
            return SimpleNamespace(run_id=kwargs['work_lock_run_id'], task_id='T-1', status='failed',
                                   worktree_path='', handoff_path='', blocked_reasons=['failed'])
        with patch.object(worker, 'load_execution_policy', return_value={'maximum_concurrent_runs': 1}), patch.object(worker, 'run_local_builder', side_effect=result):
            report = worker.process_one(self.root, task_path=task)
        self.assertEqual(report['status'], 'processed')
        record = locks.status(self.root)[0]
        self.assertEqual(record['assignment_id'], aid)
        self.assertEqual(record['run_id'], report['run_id'])
        self.assertEqual(record['state'], 'failed')
        self.assertEqual(read_assignment(self.root, aid)[0].status, 'awaiting_review')
        self.assertFalse(list((self.root / 'runtime/dispatch/local_builder_claims').glob('*.json')))

    def test_core_blocks_cross_route_before_worktree_allocation(self):
        from dispatch.local_builder_core import run_adapter_local_builder
        from dispatch.codex_local_builder import CODEX_RUN_CONFIG
        self.assignment()
        task = self.root / 'task.yaml'
        task.write_text('id: T-1\n')
        with patch('dispatch.local_builder_core.load_execution_policy', return_value={'maximum_concurrent_runs': 1}), patch('dispatch.local_builder_core.allocate_worktree') as allocator:
            result = run_adapter_local_builder(self.root, task_path=task, adapter={}, config=CODEX_RUN_CONFIG,
                                               evaluate_gates=Mock(), build_command_plan=Mock(), prepare_environment=Mock(),
                                               resolve_executable=Mock(), base_sha='base')
        self.assertEqual(result.status, 'blocked')
        self.assertIn('composer', ' '.join(result.blocked_reasons))
        allocator.assert_not_called()

    def test_direct_builder_identity_respects_assignment_override(self):
        self.assignment(logical_task_id='shared-fix')
        self.assertEqual(locks.logical_id_for_task(self.root, {'id': 'T-1'}), 'shared-fix')
        path, errors = write_assignment(self.root, task_id='T-1')
        self.assertIsNone(path)
        self.assertIn('shared-fix', ' '.join(errors))

    def test_worker_correction_does_not_claim_parent_reservation(self):
        spec = importlib.util.spec_from_file_location('worker', ROOT / 'scripts/run_local_builder_worker.py')
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        parent = self.assignment(assigned_to='codex', logical_task_id='family')
        task = self.root / 'child.yaml'
        task.write_text(yaml.safe_dump({'id': 'T-1B', 'parent_assignment_id': parent}))
        with patch.object(worker, 'load_execution_policy', return_value={'maximum_concurrent_runs': 1}), patch.object(worker, 'run_local_builder') as builder:
            report = worker.process_one(self.root, task_path=task)
        self.assertEqual(report['status'], 'skipped')
        self.assertIn(parent, report['reason'])
        self.assertEqual(read_assignment(self.root, parent)[0].status, 'pending')
        builder.assert_not_called()

    def test_terminal_run_state_releases(self):
        self.acquire()
        locks.heartbeat(self.root, 'T-1', run_id='run-1', state='accepted')
        self.assertEqual(locks.status(self.root), [])

    def test_corrupt_lock_fails_closed(self):
        path = locks.lock_path(self.root, 'T-1')
        path.parent.mkdir(parents=True)
        path.write_text('{}')
        with self.assertRaises(locks.WorkLockError):
            self.acquire()
        with self.assertRaises(locks.WorkLockError):
            locks.status(self.root)

from tests.test_physical_agent_launcher import PhysicalLauncherFixture, FakeProcess
from orchestrator.supervisor import process_wake_signal, SupervisorConfig
from orchestrator.process_monitor import MonitorResult


class SupervisorWorkLockTests(PhysicalLauncherFixture):
    def test_manual_holder_blocks_supervisor_even_for_already_claimed_assignment(self):
        claim_assignment(self.root, self.assignment_id, sync_task_yaml=False)
        locks.supersede(self.root, 'T-PHYS-LAUNCH', actor='claude', reason='manual route',
                        holder_agent='codex', route='manual', run_id='manual')
        popen = Mock()
        report = process_wake_signal(self.root, self.wake_path, config=SupervisorConfig(), popen=popen)
        self.assertEqual(report['status'], 'error')
        self.assertIn('codex', report['reason'])
        popen.assert_not_called()

    def test_supervisor_failed_run_retains_owner_and_state(self):
        monitor = Mock(return_value=MonitorResult(exit_code=1, timed_out=False, stdout='', stderr='build failed'))
        report = process_wake_signal(self.root, self.wake_path,
                                     config=SupervisorConfig(allow_codex_fallback=False),
                                     launch_plan_builder=self._plan_ok,
                                     popen=lambda *a, **k: FakeProcess(pid=123), monitor=monitor)
        record = locks.status(self.root, 'T-PHYS-LAUNCH')[0]
        self.assertEqual(record['run_id'], report['run_id'])
        self.assertEqual(record['state'], report['process_state'])
        self.assertNotEqual(record['state'], 'running')

    def test_configured_fallback_supersedes_with_audit_after_primary_exit(self):
        monitor = Mock(side_effect=[MonitorResult(exit_code=1, timed_out=False, stdout='', stderr='quota exceeded'),
                                    MonitorResult(exit_code=0, timed_out=False, stdout='done', stderr='')])
        with patch('orchestrator.supervisor.build_codex_fallback_plan', side_effect=self._plan_ok):
            report = process_wake_signal(self.root, self.wake_path,
                                         config=SupervisorConfig(allow_codex_fallback=True),
                                         launch_plan_builder=self._plan_ok,
                                         popen=lambda *a, **k: FakeProcess(pid=123), monitor=monitor)
        record = locks.status(self.root, 'T-PHYS-LAUNCH')[0]
        self.assertTrue(report['used_fallback'])
        self.assertEqual(record['holder_agent'], 'codex')
        self.assertEqual(record['run_id'], report['run_id'])
        audit = json.loads(next((locks.lock_dir(self.root) / 'audit').glob('*.json')).read_text())
        self.assertEqual(audit['actor'], 'supervisor')
        self.assertEqual(audit['prior_holder']['holder_agent'], 'composer')
        self.assertIn('primary exited', audit['reason'])


if __name__ == "__main__":
    unittest.main()
