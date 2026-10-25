"""Offline continuation, terminal exhaustion, and CLI denial regressions."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import sys
from unittest.mock import Mock, patch

from dispatch import work_lock
from dispatch.assignment_channel import read_assignment
from orchestrator.event_router import route_completion
from orchestrator.runtime_store import RunState, save_run_state
from orchestrator.supervisor import process_once
from tests.test_builder_condition_retry import ConditionRetryFixture, _monitor


class RetryLockContinuationTests(ConditionRetryFixture):
    def _config(self, **overrides):
        overrides.setdefault('grok_executable', sys.executable)
        return super()._config(**overrides)

    def tick(self, monitor=None, popen=None):
        return process_once(self.root, config=self._config(), popen=popen or self._popen,
                            launch_plan_builder=self._plan, monitor=monitor or _monitor('', exit_code=0))

    def max_turns(self):
        report = self.tick(_monitor('Stopped after reaching max turns (30)'))
        self.assertEqual(report['status'], 'requeued_continuation', report)
        return report

    def test_max_turns_continues_then_success_holds_for_review(self):
        first = self.max_turns()
        lock = work_lock.status(self.root)[0]
        self.assertEqual(lock['state'], 'reserved')
        self.assertEqual(lock['prior_run_ids'], [first['run_id']])
        for holder, assignment in [('composer', 'other'), ('codex', self.assignment_id)]:
            with self.assertRaises(work_lock.WorkLockError):
                work_lock.acquire(self.root, self.task_id, holder_agent=holder, assignment_id=assignment,
                                  route='supervisor', run_id='intruder', resume=True)
        report = self.tick()
        self.assertEqual(report['process_state'], 'completed', report)
        self.assertNotEqual(report['run_id'], first['run_id'])
        lock = work_lock.status(self.root)[0]
        self.assertEqual(lock['run_id'], report['run_id'])
        self.assertEqual(lock['state'], 'completed')
        self.assertEqual(lock['prior_run_ids'], [first['run_id']])
        self.assertEqual(read_assignment(self.root, self.assignment_id)[0].status, 'awaiting_review')

    def test_concurrent_continuations_exactly_one_wins_and_old_save_is_fenced(self):
        first = self.max_turns()
        barrier = threading.Barrier(2)

        def acquire(run):
            barrier.wait()
            try:
                work_lock.acquire(self.root, self.task_id, holder_agent='composer', route='supervisor',
                                  assignment_id=self.assignment_id, run_id=run, resume=True)
                return run
            except work_lock.WorkLockError:
                return None

        with ThreadPoolExecutor(2) as pool:
            winners = list(pool.map(acquire, ['new-a', 'new-b']))
        self.assertEqual(sum(w is not None for w in winners), 1)
        old = next(s for s in self._runs() if s.run_id == first['run_id'])
        with self.assertRaises(work_lock.WorkLockError):
            save_run_state(self.root, old)
        self.assertEqual(work_lock.status(self.root)[0]['state'], 'running')

    def test_turn_budget_exhaustion_is_one_reviewable_failure(self):
        first = self.max_turns()
        second = self.tick(_monitor('Stopped after reaching max turns (30)'))
        self.assertEqual(second['process_state'], 'blocked_external')
        self.assertEqual(read_assignment(self.root, self.assignment_id)[0].status, 'reviewable_failure')
        self.assertEqual(len(self._poke_events()), 1)
        state = next(s for s in self._runs() if s.run_id == second['run_id'])
        self.assertFalse(state.retry_eligible)
        self.assertIn('budget exhausted', state.blocked_reason)
        self.assertIn(first['run_id'], state.blocked_reason)
        self.assertIn(second['run_id'], state.blocked_reason)
        self.assertEqual(state.continuation_from_run_id, first['run_id'])
        route_completion(self.root, state)
        self.assertEqual(len(self._poke_events()), 1)
        from dispatch.orchestrator_pokes import list_orchestrator_pokes
        consumed, errors = list_orchestrator_pokes(self.root, drain=True)
        self.assertEqual(len(consumed), 1)
        self.assertEqual(errors, [])
        route_completion(self.root, state)
        self.assertEqual(self._poke_events(), [])
        self.assertEqual(work_lock.status(self.root)[0]['state'], 'blocked_external')

    def test_dead_letter_records_all_runs_and_notifies_once(self):
        with patch('orchestrator.supervisor.allocate_worktree', side_effect=ValueError('bad base SHA; fix contract')):
            for _ in range(3):
                report = self.tick()
                self.clock.advance(minutes=10)
        self.assertTrue(report['dead_lettered'])
        self.assertEqual(read_assignment(self.root, self.assignment_id)[0].status, 'reviewable_failure')
        self.assertEqual(len(self._poke_events()), 1)
        lock = work_lock.status(self.root)[0]
        self.assertEqual(lock['state'], 'failed')
        state = next(s for s in self._runs() if s.run_id == lock['run_id'])
        self.assertIn('bad base SHA', state.blocked_reason)
        for run in self._runs():
            self.assertIn(run.run_id, state.blocked_reason)
        self.tick()
        route_completion(self.root, state)
        self.assertEqual(len(self._poke_events()), 1)

    def test_interrupted_dead_letter_without_run_has_failure_notice(self):
        data = json.loads(self.wake_path.read_text())
        data['retry'] = {'attempts': 3, 'reason': 'fix missing task file'}
        self.wake_path.write_text(json.dumps(data))
        report = self.tick()
        self.assertTrue(report['dead_lettered'])
        self.assertEqual(len(self.prompts), 0)
        self.assertEqual(read_assignment(self.root, self.assignment_id)[0].status, 'reviewable_failure')
        self.assertEqual(len(self._poke_events()), 1)
        self.assertEqual(work_lock.status(self.root)[0]['state'], 'failed')

    def check_denial(self, exc, expected):
        spawn = Mock(side_effect=exc)
        report = self.tick(popen=spawn)
        self.assertEqual(report['failure_class'], expected, report)
        self.assertTrue(report['nonretryable'])
        self.assertEqual(spawn.call_count, 1)
        state = self._runs()[0]
        self.assertEqual(state.failure_class, expected)
        self.assertFalse(state.retry_eligible)
        self.assertTrue(state.blocked_executable['path'])
        result = json.loads((self.root / f'runtime/dispatch/runs/{state.run_id}/result.json').read_text())
        self.assertEqual(result['failure_class'], expected)
        self.assertEqual(read_assignment(self.root, self.assignment_id)[0].status, 'reviewable_failure')
        self.assertFalse(self.wake_path.exists())
        self.assertEqual(len(self._poke_events()), 1)
        self.assertEqual(len(list((self.root / 'runtime/dispatch/alerts').glob('*.json'))), 1)
        self.assertEqual(work_lock.status(self.root)[0]['state'], 'failed_launch')
        self._write_wake()
        self.tick(popen=spawn)
        self.assertEqual(spawn.call_count, 1)
        self.assertEqual(len(self._poke_events()), 1)

    def test_policy_denial_does_not_requeue(self):
        exc = OSError('application denied')
        exc.winerror = 4551
        self.check_denial(exc, 'BLOCKED_SECURITY_POLICY')

    def test_missing_executable_does_not_requeue(self):
        self.check_denial(FileNotFoundError('missing grok.exe'), 'CONFIG')

    def test_prelaunch_policy_exception_does_not_requeue(self):
        exc = OSError('policy denied')
        exc.winerror = 4551
        with patch.object(self, '_plan', side_effect=exc):
            report = self.tick()
        self.assertTrue(report['nonretryable'], report)
        self.assertEqual(len(self._poke_events()), 1)
        self.assertEqual(self._runs()[0].failure_class, 'BLOCKED_SECURITY_POLICY')

    def test_missing_executable_plan_is_config_without_fallback(self):
        def missing(**kwargs):
            plan = self._plan(**kwargs)
            plan.executable = ''
            plan.blocked_reasons = ['blocked_no_adapter: grok executable not found on PATH']
            return plan

        missing_path = str(self.root / 'missing-grok.exe')
        with patch('orchestrator.supervisor.build_codex_fallback_plan') as fallback:
            report = process_once(self.root, config=self._config(allow_codex_fallback=True, grok_executable=missing_path),
                                  launch_plan_builder=missing)
        fallback.assert_not_called()
        self.assertEqual(report['failure_class'], 'CONFIG')
        self.assertEqual(self._runs()[0].blocked_executable['path'], missing_path)
        self.assertFalse(self.wake_path.exists())
        self.assertEqual(len(self._poke_events()), 1)

    def test_retry_count_exhaustion_has_actionable_failure(self):
        from orchestrator.supervisor import _exhaust_assignment
        self.max_turns()
        state = self._runs()[0]
        state.process_state = 'failed'
        state.retry_count = 10
        state.retry_eligible = True
        save_run_state(self.root, state)
        report = self.tick()
        self.assertEqual(report['status'], 'skipped', report)
        self.assertEqual(read_assignment(self.root, self.assignment_id)[0].status, 'reviewable_failure')
        self.assertEqual(len(self._poke_events()), 1)
        self.assertIn('automatic retries exhausted', self._runs()[0].blocked_reason)
        _exhaust_assignment(self.root, self.assignment_id, 'automatic retries exhausted')
        self.assertEqual(len(self._poke_events()), 1)

    def test_evidence_terminal_shape_is_resumed_before_refusal_sequence(self):
        evidence = Path(__file__).resolve().parents[1] / 'runtime/dispatch/m1-33/evidence'
        result = json.loads((evidence / 'grok_max_turns_result.json').read_text())
        old_lock = json.loads((evidence / 'lock_after.json').read_text())
        refusal = json.loads((evidence / 'refused_relaunch.json').read_text())
        dead = json.loads((evidence / 'dead_letter.json').read_text())
        self.assertEqual(dead['retry']['attempts'], 3)
        self.assertIn('explicit release', refusal['blocked_reason'])
        state = RunState(run_id=result['run_id'], assignment_id=self.assignment_id, task_id=self.task_id,
                         logical_task_id=self.task_id, assigned_agent=result['assigned_agent'],
                         adapter=result['adapter_id'], process_state=result['process_state'],
                         retry_eligible=result['retry_eligible'], worktree=str(self.worktree), branch=result['branch'])
        # Serialize the pre-fix shapes, without touching any referenced live paths.
        run_dir = self.root / 'runtime/dispatch/runs' / state.run_id
        run_dir.mkdir()
        (run_dir / 'supervisor_run.json').write_text(json.dumps(state.to_dict()))
        refused_dir = run_dir.parent / refusal['run_id']
        refused_dir.mkdir()
        refusal.update(assignment_id=self.assignment_id, task_id=self.task_id,
                       wake_signal_path=str(self.wake_path))
        (refused_dir / 'supervisor_run.json').write_text(json.dumps(refusal))
        old_lock.update(logical_task_id=self.task_id, assignment_id=self.assignment_id)
        work_lock.lock_path(self.root, self.task_id).write_text(json.dumps(old_lock))
        from dispatch.assignment_channel import set_assignment_status
        set_assignment_status(self.root, self.assignment_id, 'building')
        report = self.tick()
        self.assertEqual(report['process_state'], 'completed', report)
        self.assertEqual(len(self.prompts), 1)
        self.assertIn(state.run_id, work_lock.status(self.root)[0]['prior_run_ids'])
        self.assertFalse(list((self.root / 'runtime/dispatch/wake_queue/dead_letter').rglob('*.json')))
