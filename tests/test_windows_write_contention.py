"""Offline reproduction of Windows sharing failures and mid-monitor crashes."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from dispatch import atomic_io, work_lock
from orchestrator import layer_heartbeat
from orchestrator.failure_classify import classify_process_output
from orchestrator.process_monitor import monitor_process
from orchestrator.runtime_store import RunState, load_run_state, save_run_state
from orchestrator.supervisor import process_once, recover_orphans
from dispatch.agent_context_bundle import _atomic_write
from tests.test_builder_condition_retry import ConditionRetryFixture, _monitor


def sharing_error(code=5, cls=PermissionError):
    error = cls('simulated sharing violation')
    error.winerror = code
    return error


class AtomicContentionTests(unittest.TestCase):
    def test_context_writer_uses_same_retry_and_preserves_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'context.md'
            replace = os.replace
            with patch.object(atomic_io.os, 'replace') as mocked, \
                 patch.object(atomic_io.time, 'sleep'):
                def attempt(source, destination):
                    if mocked.call_count == 1:
                        raise sharing_error()
                    replace(source, destination)
                mocked.side_effect = attempt
                _atomic_write(path, 'context: \u0219\n')
            self.assertEqual(path.read_bytes(), 'context: \u0219\n'.encode('utf-8'))

    def test_retries_windows_errors_then_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            for code, cls in ((5, PermissionError), (32, PermissionError), (32, OSError), (33, OSError)):
                with self.subTest(code=code, cls=cls), patch.object(
                    atomic_io.os, 'replace', side_effect=[sharing_error(code, cls), sharing_error(code, cls), None]
                ) as replace, patch.object(atomic_io.time, 'sleep'):
                    atomic_io.atomic_write_json(path, {'new': True})
                    self.assertEqual(replace.call_count, 3)

    def test_budget_preserves_destination_and_cleans_tmp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            path.write_text('{"old": true}')
            elapsed = [0.0]
            def sleep(delay):
                elapsed[0] += delay
            with patch.object(atomic_io.os, 'replace', side_effect=sharing_error()), \
                 patch.object(atomic_io.time, 'monotonic', side_effect=lambda: elapsed[0]), \
                 patch.object(atomic_io.time, 'sleep', side_effect=sleep):
                with self.assertRaises(PermissionError):
                    atomic_io.atomic_write_json(path, {'new': True})
            self.assertGreaterEqual(elapsed[0], 2)
            self.assertLessEqual(elapsed[0], 3)
            self.assertEqual(json.loads(path.read_text()), {'old': True})
            self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_posix_permission_error_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(atomic_io.os, 'replace', side_effect=PermissionError('denied')) as replace, \
             patch.object(atomic_io.time, 'sleep') as sleep:
            with self.assertRaises(PermissionError):
                atomic_io.atomic_write_json(Path(tmp) / 'state.json', {})
            self.assertEqual(replace.call_count, 1)
            sleep.assert_not_called()

    def test_concurrent_writers_have_unique_complete_temps(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            barrier = threading.Barrier(6)
            seen = []
            replace = os.replace
            def synchronized(source, destination):
                if str(source) not in {name for name, _ in seen}:
                    seen.append((str(source), json.loads(Path(source).read_text())))
                    barrier.wait(timeout=10)
                replace(source, destination)
            with patch.object(atomic_io.os, 'replace', side_effect=synchronized), ThreadPoolExecutor(6) as pool:
                list(pool.map(lambda i: atomic_io.atomic_write_json(path, {'writer': i}), range(6)))
            self.assertEqual(len({name for name, _ in seen}), 6)
            self.assertEqual({data['writer'] for _, data in seen}, set(range(6)))
            self.assertIn(json.loads(path.read_text())['writer'], range(6))
            self.assertEqual(list(path.parent.glob('*.tmp')), [])


class LoopContentionTests(unittest.TestCase):
    def test_heartbeat_failure_is_rate_limited_and_loop_continues(self):
        with patch.dict(os.environ, AGENTIC_LAYER_HEARTBEAT='unused.json'), \
             patch.object(layer_heartbeat, '_last_write', 0), \
             patch.object(layer_heartbeat, '_last_warning', None), \
             patch.object(layer_heartbeat.time, 'monotonic', return_value=100), \
             patch.object(layer_heartbeat, 'atomic_write_json', side_effect=sharing_error()) as write, \
             self.assertLogs('orchestrator.layer_heartbeat', level='WARNING') as logs:
            for _ in range(5):
                layer_heartbeat.tick(progress=True)
            self.assertEqual(write.call_count, 5)
            self.assertEqual(len(logs.output), 1)

    def test_monitor_defers_failed_persist_and_keeps_quota_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stdout = root / 'stdout.log'
            stdout.write_text('API error status 402 Payment Required')
            state = RunState('r', 'a', 't', 'composer', 'composer-restricted', process_state='running', pid=123)
            persist = Mock(side_effect=[None, sharing_error(), None])
            with patch('orchestrator.process_monitor.terminate_owned'), \
                 self.assertLogs('orchestrator.process_monitor', level='WARNING'):
                result = monitor_process(Mock(), state=state, repo_root=root,
                    stdout_path=stdout, stderr_path=root / 'stderr.log', timeout_seconds=60,
                    poll_fn=Mock(side_effect=[None, None, 1]), sleep_fn=lambda _: None,
                    persist_fn=persist)
            self.assertEqual(persist.call_count, 3)
            self.assertEqual(classify_process_output(agent='composer', adapter=state.adapter,
                exit_code=result.exit_code, stdout=result.stdout).process_state, 'blocked_quota')


class OrphanContentionTests(ConditionRetryFixture):
    def test_monitor_write_failure_reaches_normal_quota_schedule(self):
        writes = [0]
        def persist(root, state):
            writes[0] += 1
            if writes[0] == 2:
                raise sharing_error()
            save_run_state(root, state)
        def monitor(process, **kwargs):
            kwargs['stdout_path'].write_text('API error status 402 Payment Required')
            return monitor_process(process, **kwargs, poll_fn=Mock(side_effect=[None, None, 1]),
                                   persist_fn=persist, sleep_fn=lambda _: None)
        with patch('orchestrator.process_monitor.terminate_owned'), \
             self.assertLogs('orchestrator.process_monitor', level='WARNING'):
            result = process_once(self.root, config=self._config(), popen=self._popen,
                                  launch_plan_builder=self._plan, monitor=monitor)
        self.assertEqual(result['status'], 'blocked_quota')
        state = load_run_state(self.root, result['run_id'])
        self.assertEqual(state.blocked_on, 'quota:grok')
        self.assertTrue(state.next_eligible_at)
        self.assertEqual(writes[0], 3)

    def crash(self, output='API error status 402 Payment Required'):
        def crash_monitor(process, **kwargs):
            kwargs['stdout_path'].write_text(output)
            raise RuntimeError('simulated layer crash')
        with patch('orchestrator.supervisor.ownership_metadata', return_value={'process_start_time': 'original'}):
            with self.assertRaisesRegex(RuntimeError, 'simulated layer crash'):
                process_once(self.root, config=self._config(), popen=self._popen,
                             launch_plan_builder=self._plan, monitor=crash_monitor)
        return self._runs()[0]

    def test_crash_salvages_quota_then_relaunches_once_with_lock(self):
        crashed = self.crash()
        self.assertEqual(crashed.process_state, 'running')
        with patch('orchestrator.supervisor.pid_is_alive', return_value=False) as alive:
            recovered = recover_orphans(self.root, config=self._config())
        alive.assert_called_with(crashed.pid, 'original')
        self.assertEqual(recovered[0]['status'], 'blocked_quota')
        blocked = load_run_state(self.root, crashed.run_id)
        self.assertIsNone(blocked.exit_code)
        self.assertEqual(blocked.blocked_on, 'quota:grok')
        self.assertTrue(blocked.next_eligible_at)
        self.assertEqual(work_lock.status(self.root)[0]['run_id'], crashed.run_id)
        config = self._config(condition_probe=lambda _: False)
        kwargs = dict(config=config, popen=self._popen, launch_plan_builder=self._plan,
                      monitor=_monitor('done', exit_code=0, activity=1))
        self.assertFalse(process_once(self.root, **kwargs).get('process_started'))
        self.clock.advance(minutes=15)
        result = process_once(self.root, **kwargs)
        self.assertEqual(result['status'], 'completed', result)
        latest = load_run_state(self.root, result['run_id'])
        self.assertEqual(latest.condition_retry_from_run_id, crashed.run_id)
        self.assertEqual(latest.attempts, 1)
        self.assertEqual(work_lock.status(self.root)[0]['run_id'], latest.run_id)
        process_once(self.root, **kwargs)
        self.assertEqual(len(self._runs()), 2)
        self.assertEqual(sum(r.process_state == 'completed' for r in self._runs()), 1)

    def test_unclassifiable_orphan_releases_only_own_lock_with_audit(self):
        crashed = self.crash('unclassifiable output')
        with patch('orchestrator.supervisor.pid_is_alive', return_value=False):
            recover_orphans(self.root, config=self._config())
        self.assertEqual(load_run_state(self.root, crashed.run_id).process_state, 'orphaned')
        self.assertEqual(work_lock.status(self.root), [])
        audits = [json.loads(p.read_text()) for p in (work_lock.lock_dir(self.root) / 'audit').glob('*.json')]
        self.assertTrue(any(a['reason'] == 'orphan_recovered' and a['prior_holder']['run_id'] == crashed.run_id for a in audits))

    def test_orphan_never_touches_replacement_holder(self):
        crashed = self.crash('unclassifiable output')
        work_lock.supersede(self.root, self.task_id, actor='claude', reason='explicit replacement',
                            holder_agent='codex', route='manual', run_id='replacement')
        replacement = RunState('replacement', '', self.task_id, 'codex', 'codex-restricted',
                               logical_task_id=self.task_id, process_state='completed')
        save_run_state(self.root, replacement)
        before = work_lock.lock_path(self.root, self.task_id).read_bytes()
        with patch('orchestrator.supervisor.pid_is_alive', return_value=False):
            recover_orphans(self.root, config=self._config())
        self.assertEqual(work_lock.lock_path(self.root, self.task_id).read_bytes(), before)
        holder = work_lock.status(self.root)[0]
        self.assertEqual(holder['run_id'], 'replacement')
        self.assertEqual(holder['holder_agent'], 'codex')
        self.assertEqual(load_run_state(self.root, crashed.run_id).process_state, 'orphaned')

    def test_unknown_or_live_pid_remains_running(self):
        crashed = self.crash()
        before = work_lock.lock_path(self.root, self.task_id).read_bytes()
        for alive in (True, None):
            with self.subTest(alive=alive), patch('orchestrator.supervisor.pid_is_alive', return_value=alive):
                self.assertEqual(recover_orphans(self.root, config=self._config()), [])
            self.assertEqual(load_run_state(self.root, crashed.run_id).process_state, 'running')
            self.assertEqual(work_lock.lock_path(self.root, self.task_id).read_bytes(), before)

    def test_authentication_salvage_uses_normal_retry_after(self):
        crashed = self.crash(json.dumps({'type': 'error', 'message': '401 unauthorized; retry-after: 60'}))
        with patch('orchestrator.supervisor.pid_is_alive', return_value=False), \
             patch('orchestrator.failure_classify._now', return_value=self.clock()):
            recover_orphans(self.root, config=self._config())
        state = load_run_state(self.root, crashed.run_id)
        self.assertEqual(state.process_state, 'blocked_authentication')
        self.assertEqual(state.blocked_on, 'auth:grok')
        self.assertEqual(state.next_eligible_at, '2026-10-21T00:01:00Z')
        self.assertEqual(state.failure_fingerprint['cli_exit_code'], None)

    def test_success_narration_is_not_salvaged_as_provider_failure(self):
        crashed = self.crash(json.dumps({'type': 'tool_result', 'is_error': True,
                                       'error': 'quota 402 authentication'}))
        with patch('orchestrator.supervisor.pid_is_alive', return_value=False):
            recover_orphans(self.root, config=self._config())
        self.assertEqual(load_run_state(self.root, crashed.run_id).process_state, 'orphaned')

    def test_terminal_record_is_ghost_alert_without_stealing(self):
        crashed = self.crash('unclassifiable output')
        for status in ('orphaned', 'failed_launch', 'blocked_external'):
            with self.subTest(status=status):
                crashed.process_state = status
                save_run_state(self.root, crashed)
                with patch('orchestrator.supervisor.pid_is_alive', return_value=False):
                    recover_orphans(self.root, config=self._config())
                lock = work_lock.status(self.root)[0]
                self.assertEqual(lock['run_id'], crashed.run_id)
                self.assertEqual(lock['stale_reason'], 'ghost_holder')
                alerts = json.loads((self.root / 'runtime/dispatch/supervisor_status.json').read_text())['work_lock_alerts']
                self.assertEqual(alerts[0]['reason'], 'ghost_holder')

    def test_terminal_result_without_supervisor_record_is_ghost(self):
        crashed = self.crash('unclassifiable output')
        crashed.process_state = 'blocked_external'
        save_run_state(self.root, crashed)
        (self.root / 'runtime/dispatch/runs' / crashed.run_id / 'supervisor_run.json').unlink()
        with patch('orchestrator.supervisor.pid_is_alive', return_value=False):
            alerts = recover_orphans(self.root, config=self._config())
        self.assertEqual(alerts[0]['reason'], 'ghost_holder')
        self.assertEqual(work_lock.status(self.root)[0]['run_id'], crashed.run_id)

    def test_terminal_live_process_is_not_ghost(self):
        crashed = self.crash()
        crashed.process_state = 'blocked_external'
        save_run_state(self.root, crashed)
        before = work_lock.lock_path(self.root, self.task_id).read_bytes()
        with patch('orchestrator.supervisor.pid_is_alive', return_value=True):
            self.assertEqual(recover_orphans(self.root, config=self._config()), [])
        self.assertEqual(work_lock.lock_path(self.root, self.task_id).read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
