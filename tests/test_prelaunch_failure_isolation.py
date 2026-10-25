"""Offline drill regressions for launch cleanup and scheduling fairness."""
import json
from unittest.mock import patch

from tests.test_builder_condition_retry import ConditionRetryFixture, _monitor
from dispatch import work_lock
from dispatch.worktree_allocator import allocate_worktree
from orchestrator.supervisor import process_once, recover_orphans


class PrelaunchIsolationTests(ConditionRetryFixture):
    def tick(self, **kwargs):
        return process_once(self.root, config=self._config(), popen=self._popen,
                            launch_plan_builder=self._plan, monitor=_monitor('', exit_code=0), **kwargs)

    def poison_allocator(self):
        self.allocator.stop()
        inbox = self.root / f'runtime/dispatch/assignments/inbox/{self.assignment_id}.json'
        data = json.loads(inbox.read_text())
        data['base_sha'] = 'HEAD'
        data['status'] = 'changes_requested'
        inbox.write_text(json.dumps(data))

        def allocate(root, **kwargs):
            with patch('dispatch.worktree_allocator.resolve_worktree_root', return_value=self.root / 'allocations'):
                return allocate_worktree(root, **kwargs)

        return patch('orchestrator.supervisor.allocate_worktree', side_effect=allocate)

    def test_invalid_base_releases_attempt_lock_with_audit(self):
        with self.poison_allocator():
            report = self.tick()
        self.assertEqual(report['status'], 'error')
        self.assertIn("invalid base_sha format: 'HEAD'", report['reason'])
        self.assertEqual(work_lock.status(self.root), [])
        audit = list((self.root / 'runtime/dispatch/locks/audit').glob('*.json'))
        self.assertIn('pre-launch', audit[0].read_text())
        self.assertTrue(self._runs())
        self.assertEqual(self._runs()[0].process_state, 'failed_launch')

    def test_poison_backoff_then_dead_letter(self):
        with self.poison_allocator() as allocator:
            self.tick()
            self.tick()
            self.assertEqual(allocator.call_count, 1)
            for _ in range(2):
                self.clock.advance(minutes=10)
                self.tick()
            self.assertEqual(allocator.call_count, 3)
            self.tick()
            self.assertEqual(allocator.call_count, 3)
        self.assertFalse(self.wake_path.exists())
        dead = list((self.root / 'runtime/dispatch/wake_queue/dead_letter').rglob('*.json'))
        self.assertEqual(len(dead), 1)
        data = json.loads(dead[0].read_text())
        self.assertEqual(data['retry']['attempts'], 3)
        self.assertIn('HEAD', data['retry']['reason'])
        self.assertTrue(data['retry']['first_failed_at'])
        status = json.loads((self.root / 'runtime/dispatch/supervisor_status.json').read_text())
        self.assertTrue(status['wake_alerts'])

    def test_due_quota_relaunches_with_poison_in_queue(self):
        report = process_once(self.root, config=self._config(), popen=self._popen,
                              launch_plan_builder=self._plan, monitor=_monitor('quota exceeded'))
        self.assertEqual(report['process_state'], 'blocked_quota')
        poison = self.wake_path.parent / '000-poison.json'
        poison.write_text('{}')
        self.clock.advance(minutes=15)
        report = self.tick()
        self.assertEqual(report['process_state'], 'completed', report)
        self.assertEqual(len(self.prompts), 2)

    def test_poison_does_not_hide_two_valid_wakes(self):
        poison = self.wake_path.parent / '000-poison.json'
        poison.write_text('{}')
        # Independent valid assignments must launch once each, on successive ticks.
        second = self.wake_path.parent / 'zzz-second.json'
        source = self.root / f'runtime/dispatch/assignments/inbox/{self.assignment_id}.json'
        assignment = json.loads(source.read_text())
        assignment.update(assignment_id='second', task_id='T-SECOND', logical_task_id='T-SECOND',
                          task_path='tasks/active/T-SECOND.yaml', new_branch='agent/composer/T-SECOND')
        source.with_name('second.json').write_text(json.dumps(assignment))
        task = self.root / 'tasks/active/T-COND.yaml'
        task.with_name('T-SECOND.yaml').write_text(task.read_text().replace('T-COND', 'T-SECOND'))
        wake = json.loads(self.wake_path.read_text())
        wake.update(assignment_id='second', task_id='T-SECOND', task_path='tasks/active/T-SECOND.yaml')
        second.write_text(json.dumps(wake))
        self.assertEqual(self.tick()['process_state'], 'completed')
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(self.tick()['process_state'], 'completed')
        self.assertEqual(len(self.prompts), 2)

    def test_launch_exception_releases_lock_and_retries_same_assignment(self):
        with patch('orchestrator.supervisor.launch_process', side_effect=OSError('cannot spawn')):
            self.assertEqual(self.tick()['status'], 'error')
        self.assertEqual(work_lock.status(self.root), [])
        self.clock.advance(minutes=1)
        self.assertEqual(self.tick()['process_state'], 'completed')

    def test_missing_adapter_dead_letters_and_retains_reviewable_failure_lock(self):
        def unavailable(**kwargs):
            plan = self._plan(**kwargs)
            plan.blocked_reasons = ['blocked_no_adapter: unavailable']
            return plan

        with patch.object(self, '_plan', side_effect=RuntimeError('task load failed')):
            self.assertEqual(self.tick()['status'], 'error')
        self.assertEqual(work_lock.status(self.root), [])
        for attempt in range(2):
            self.clock.advance(minutes=10)
            report = process_once(self.root, config=self._config(), launch_plan_builder=unavailable)
            self.assertEqual(report['status'], 'blocked', report)
            if attempt == 0:
                self.assertEqual(work_lock.status(self.root), [])
        self.assertTrue(report['dead_lettered'])
        self.assertEqual(work_lock.status(self.root)[0]['state'], 'failed')

    def test_spawn_error_result_releases_lock(self):
        with patch('orchestrator.supervisor.launch_process', return_value=(None, 'spawn failed')):
            self.assertEqual(self.tick()['status'], 'failed_launch')
        self.assertEqual(work_lock.status(self.root), [])
        self.clock.advance(minutes=1)
        self.assertEqual(self.tick()['process_state'], 'completed')

    def test_prelaunch_cleanup_cannot_release_replacement_holder(self):
        def superseded(**kwargs):
            work_lock.supersede(self.root, self.task_id, actor='claude', reason='replacement',
                                holder_agent='codex', route='test', assignment_id='replacement', run_id='new')
            raise ValueError('adapter resolution failed after supersede')

        report = process_once(self.root, config=self._config(), launch_plan_builder=superseded)
        self.assertEqual(report['status'], 'error')
        self.assertTrue(report['cleanup_fenced'])
        self.assertEqual(work_lock.status(self.root)[0]['run_id'], 'new')

    def test_deferred_head_does_not_hide_valid_wake(self):
        import orchestrator.supervisor as supervisor
        head = self.wake_path.parent / '000-deferred.json'
        head.write_text('{}')
        real = supervisor.process_wake_signal

        def launch(root, path, **kwargs):
            if path == head:
                return {'status': 'deferred', 'reason': 'test capacity guard'}
            return real(root, path, **kwargs)

        with patch.object(supervisor, 'process_wake_signal', side_effect=launch):
            self.assertEqual(self.tick()['process_state'], 'completed')

    def test_rechecks_conditions_on_each_tick_with_valid_wakes(self):
        with patch('orchestrator.supervisor.reevaluate_blocked_builders', return_value=None) as reevaluate:
            self.tick()
            self._write_wake()
            self.tick()
        self.assertEqual(reevaluate.call_count, 2)

    def test_tick_does_not_launch_post_process_fallback(self):
        with patch('orchestrator.supervisor.build_codex_fallback_plan') as fallback:
            process_once(self.root, config=self._config(allow_codex_fallback=True),
                         popen=self._popen, launch_plan_builder=self._plan,
                         monitor=_monitor('quota exceeded'))
        fallback.assert_not_called()
        self.assertEqual(len(self.prompts), 1)

    def test_malformed_wake_is_bounded(self):
        self.wake_path.write_text('{invalid json')
        for _ in range(3):
            self.tick()
            self.clock.advance(minutes=10)
        self.assertFalse(self.wake_path.exists())

    def test_restart_finishes_exhausted_move_without_fourth_attempt(self):
        data = json.loads(self.wake_path.read_text())
        data['retry'] = {'attempts': 3, 'reason': 'invalid base',
                         'first_failed_at': self.clock().isoformat(),
                         'last_failed_at': self.clock().isoformat()}
        self.wake_path.write_text(json.dumps(data))
        with patch('orchestrator.supervisor.allocate_worktree') as allocate:
            self.assertTrue(self.tick()['dead_lettered'])
        allocate.assert_not_called()
        self.assertFalse(self.wake_path.exists())

    def test_live_lease_without_run_record_is_not_declared_ghost(self):
        from orchestrator.leases import try_acquire_concurrency, heartbeat_lease
        work_lock.supersede(self.root, self.task_id, actor='test', reason='inject live holder',
                            holder_agent='composer', route='supervisor',
                            assignment_id=self.assignment_id, run_id='live-run')
        try_acquire_concurrency(self.root, assignment_id=self.assignment_id, run_id='live-run', holder='test')
        heartbeat_lease(self.root, self.assignment_id, pid=4242)
        with patch('orchestrator.supervisor.pid_is_alive', return_value=True):
            self.assertEqual(recover_orphans(self.root), [])
        self.assertNotIn('stale_reason', work_lock.status(self.root)[0])

    def test_ghost_reported_stale_without_stealing(self):
        work_lock.supersede(self.root, self.task_id, actor='test', reason='inject ghost', holder_agent='composer', route='supervisor',
                          assignment_id=self.assignment_id, run_id='missing-run')
        reports = recover_orphans(self.root)
        self.assertEqual(reports[0]['reason'], 'ghost_holder')
        lock = work_lock.status(self.root)[0]
        self.assertTrue(lock['stale'])
        self.assertEqual(lock['stale_reason'], 'ghost_holder')
        with self.assertRaises(work_lock.WorkLockError):
            work_lock.acquire(self.root, self.task_id, holder_agent='composer', route='supervisor',
                              assignment_id=self.assignment_id, run_id='replacement', resume=True)
        status = json.loads((self.root / 'runtime/dispatch/supervisor_status.json').read_text())
        self.assertTrue(status['work_lock_alerts'])
