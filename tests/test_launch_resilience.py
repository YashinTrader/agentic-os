"""Deterministic launch resilience tests; no real processes or waits."""
import json
import random
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator.layer_supervisor import LayerSupervisor
from orchestrator.launch_failures import classify_launch_failure, executable_identity
from orchestrator.root_restart_guard import RootRestartGuard
from scripts.stop_supervisor import reset_resilience
from tests.test_layer_supervisor import FakeProcess


class LaunchResilienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "runtime").mkdir()
        self.exe = self.root / 'runtime.exe'
        self.exe.write_bytes(b'first runtime')
        self.now = 0
        self.supervisor = LayerSupervisor(self.root, {'builder': [str(self.exe)]},
                                          clock=lambda: self.now, wall_clock=lambda: self.now,
                                          rng=random.Random(7))

    def denial(self):
        exc = OSError('blocked')
        exc.winerror = 4551
        return exc

    def test_classification(self):
        for code in (4551, 1260, 4556, 225):
            exc = OSError('blocked')
            exc.winerror = code
            self.assertEqual(classify_launch_failure(exc), 'BLOCKED_SECURITY_POLICY')
        for text in ('Application Control policy has blocked', 'blocked by group policy',
                     'Code Integrity', 'did not meet the Enterprise signing level'):
            self.assertEqual(classify_launch_failure(stderr=text.upper()), 'BLOCKED_SECURITY_POLICY')
        for code in (2, 3):
            exc = OSError('missing')
            exc.winerror = code
            self.assertEqual(classify_launch_failure(exc), 'CONFIG')
        self.assertEqual(classify_launch_failure(FileNotFoundError()), 'CONFIG')
        self.assertEqual(classify_launch_failure(OSError('other')), 'TRANSIENT')

    def test_stderr_policy_and_persistence(self):
        child = self.supervisor.children['builder']
        self.supervisor.failed(child, 0, 1, 'exited', 'Code Integrity denied runtime')
        self.supervisor.save()
        reloaded = LayerSupervisor(self.root, {'builder': [str(self.exe)]}, clock=lambda: self.now)
        with patch('orchestrator.layer_supervisor.owned_popen') as launch:
            for second in range(0, 86400, 60):
                self.now = second
                reloaded.supervise_child(reloaded.children['builder'], second)
            launch.assert_not_called()
        self.assertEqual(child.status['exits'][-1]['failure_class'], 'BLOCKED_SECURITY_POLICY')

    def test_identity_change_probe_success(self):
        with patch('orchestrator.layer_supervisor.owned_popen', side_effect=[self.denial(), FakeProcess(11)]) as launch:
            self.supervisor.step()
            self.exe.write_bytes(b'replacement signed runtime')
            self.now = 59
            self.supervisor.step()
            self.assertEqual(launch.call_count, 1)
            self.now = 60
            self.supervisor.step()
            self.assertEqual(launch.call_count, 2)
            child = self.supervisor.children['builder']
            hb = {'token': child.token, 'ticks': 1, 'pid': None}
            with patch('orchestrator.layer_supervisor.read_heartbeat', return_value=hb):
                self.supervisor.step()
            self.assertEqual(child.status['state'], 'running')

    def test_reset_audited_consumed_once_and_no_duplicate_alert(self):
        with patch('orchestrator.layer_supervisor.owned_popen', side_effect=self.denial()) as launch:
            self.supervisor.step()
            self.assertEqual(reset_resilience(self.root, 'operator', 'runtime now permitted', 'builder'), 0)
            self.supervisor.step()
            for second in range(60, 600, 60):
                self.now = second
                self.supervisor.step()
            self.assertEqual(launch.call_count, 2)
        audits = list((self.supervisor.path.parent / 'audit').glob('*.json'))
        self.assertEqual(len(audits), 1)
        self.assertEqual(json.loads(audits[0].read_text())['exit_code'], 0)
        alerts = [json.loads(p.read_text()) for p in (self.root / 'runtime/dispatch/alerts').glob('*.json')]
        self.assertEqual(sum(a.get('layer') == 'builder' for a in alerts), 1)

    def test_changed_identity_denied_again_blocks_one_probe(self):
        with patch('orchestrator.layer_supervisor.owned_popen', side_effect=self.denial()) as launch:
            self.supervisor.step()
            self.exe.write_bytes(b'new runtime identity')
            for second in range(60, 3600, 60):
                self.now = second
                self.supervisor.step()
            self.assertEqual(launch.call_count, 2)
        alerts = [json.loads(p.read_text()) for p in (self.root / 'runtime/dispatch/alerts').glob('*.json')]
        self.assertEqual(sum(a.get('layer') == 'builder' for a in alerts), 2)  # one per identity

    def test_config_waits_for_executable_to_appear(self):
        self.exe.unlink()
        with patch('orchestrator.layer_supervisor.owned_popen', side_effect=[FileNotFoundError(), FakeProcess(11)]) as launch:
            self.supervisor.step()
            self.now = 60
            self.supervisor.step()
            self.assertEqual(launch.call_count, 1)
            self.exe.write_bytes(b'installed')
            self.now = 120
            self.supervisor.step()
            self.assertEqual(launch.call_count, 2)

    def test_identity_hash_only_after_stat_change(self):
        old = executable_identity(str(self.exe), self.root)
        with patch('orchestrator.launch_failures.hashlib.file_digest', side_effect=AssertionError('rehash')):
            self.assertEqual(executable_identity(str(self.exe), self.root, old), old)

    def test_removed_policy_executable_reappearing_unchanged_is_not_a_probe(self):
        with patch('orchestrator.layer_supervisor.owned_popen', side_effect=self.denial()) as launch:
            self.supervisor.step()
            contents = self.exe.read_bytes()
            self.exe.unlink()
            self.now = 60
            self.supervisor.step()
            self.exe.write_bytes(contents)
            self.now = 120
            self.supervisor.step()
            self.assertEqual(launch.call_count, 1)

    def test_transient_jitter_and_half_open_bounds_over_day(self):
        child = self.supervisor.children['builder']
        delays = []
        cooldowns = []
        with patch('orchestrator.layer_supervisor.owned_popen', side_effect=OSError('temporary')) as launch:
            while self.now < 86400:
                self.supervisor.supervise_child(child, self.now)
                if child.status.get('circuit_open'):
                    cooldowns.append(child.cooldown)
                    self.now = child.probe_due
                else:
                    delays.append(child.due - self.now)
                    self.now = child.due
            self.assertLessEqual(launch.call_count, 16)
        self.assertEqual(len(delays), 5)
        for i, delay in enumerate(delays):
            self.assertGreaterEqual(delay, 2)
            self.assertLessEqual(delay, min(300, 2 * 2 ** i))
        self.assertEqual(cooldowns[:5], [900, 1800, 3600, 7200, 14400])
        self.assertEqual(cooldowns, sorted(cooldowns))
        self.assertLessEqual(max(cooldowns), 14400)

    def test_idle_write_budgets_and_sleep(self):
        child = self.supervisor.children['builder']
        child.status.update(state='running')
        with patch.object(self.supervisor, 'supervise_child'), patch('orchestrator.layer_supervisor.atomic_write_json') as write:
            for second in range(600):
                self.now = second
                self.supervisor.step()
            self.assertLessEqual(write.call_count, 600 * .2)
            self.assertEqual(self.supervisor.sleep_seconds(), 1)
            child.status.update(state='starting')
            self.assertEqual(self.supervisor.sleep_seconds(), .25)
            child.status.update(state='crash_loop', circuit_open=True)
            self.supervisor.step()
            write.reset_mock()
            for second in range(600, 1200):
                self.now = second
                self.supervisor.step()
            self.assertLessEqual(write.call_count, 10)
            self.assertEqual(self.supervisor.sleep_seconds(), 5)
        self.assertEqual(self.supervisor._saved_content['state'], 'parked')

    def test_full_parked_steps_have_negligible_cpu_and_no_rehash(self):
        with patch('orchestrator.layer_supervisor.owned_popen', side_effect=self.denial()):
            self.supervisor.step()
        started = time.process_time()
        with patch('orchestrator.layer_supervisor.atomic_write_json') as write, \
             patch('orchestrator.launch_failures.hashlib.file_digest', side_effect=AssertionError('unchanged hash')):
            for step in range(1, 601):
                self.now = step * 5
                self.supervisor.step()
            self.assertEqual(write.call_count, 50)
        # 600 complete parked iterations represent 3000 seconds of root life.
        # Two CPU seconds is <0.07% CPU at the mandated five-second cadence.
        self.assertLess(time.process_time() - started, 2)

    def test_continuously_ticking_healthy_idle_budget(self):
        child = self.supervisor.children['builder']
        child.status.update(state='running', alive=True, ticking=True)
        def heartbeat(current, now):
            current.status.update(ticks=int(now), last_tick_at=str(now))
        with patch.object(self.supervisor, 'supervise_child', side_effect=heartbeat), \
             patch('orchestrator.layer_supervisor.atomic_write_json') as write:
            for second in range(600):
                self.now = second
                self.supervisor.step()
            self.assertEqual(write.call_count, 120)
            # Failures remain immediately visible inside the batching interval.
            self.now = 599.5
            child.status.update(state='crash_loop', circuit_open=True)
            self.supervisor.step()
            self.assertEqual(write.call_count, 121)

    def test_transient_probe_deadline_survives_root_restart(self):
        child = self.supervisor.children['builder']
        for _ in range(6):
            self.supervisor.failed(child, 0, 1, 'exited', '')
        self.supervisor.save()
        reloaded = LayerSupervisor(self.root, {'builder': [str(self.exe)]},
                                   clock=lambda: self.now, wall_clock=lambda: self.now)
        with patch('orchestrator.layer_supervisor.owned_popen', side_effect=OSError('temporary')) as launch:
            self.now = 899
            reloaded.step()
            launch.assert_not_called()
            self.now = 900
            reloaded.step()
            self.assertEqual(launch.call_count, 1)
        self.assertEqual(reloaded.children['builder'].cooldown, 1800)

    def test_parked_shutdown_clean(self):
        with patch('orchestrator.layer_supervisor.owned_popen', side_effect=self.denial()):
            self.supervisor.step()
        from dispatch.atomic_io import atomic_write_json
        request = {'instance_token': self.supervisor.instance_token, 'requester': 'operator',
                   'reason': 'planned stop', 'token': 'stop-token', 'at': 'now'}
        atomic_write_json(self.supervisor.path.parent / 'stop_request.json', request)
        self.supervisor.step()
        self.assertTrue(self.supervisor.stop_requested)
        self.supervisor.shutdown()
        saved = json.loads(self.supervisor.path.read_text())
        self.assertEqual(saved['state'], 'stopped_by_request')
        self.assertFalse(saved['children']['builder']['alive'])
        reloaded = LayerSupervisor(self.root, {'builder': [str(self.exe)]})
        self.assertEqual(reloaded.children['builder'].status['state'], 'blocked_security_policy')

    def test_root_guard_budget_cooldown_and_reset_audit(self):
        guards = [RootRestartGuard(self.root, lambda: self.now) for _ in range(4)]
        for guard in guards[:3]:
            self.assertTrue(guard.start())
        self.assertFalse(guards[3].start())
        self.assertFalse(guards[3].start())
        data = json.loads(guards[3].path.read_text())
        self.assertEqual(data['next_probe_at'], 1800)
        self.now = 1801
        self.assertTrue(guards[3].start())
        self.assertFalse(RootRestartGuard(self.root, lambda: self.now).start())
        self.assertEqual(json.loads(guards[3].path.read_text())['cooldown'], 3600)
        for expected in (7200, 14400, 28800, 28800):
            self.now = json.loads(guards[3].path.read_text())['next_probe_at'] + 1
            self.assertTrue(RootRestartGuard(self.root, lambda: self.now).start())
            self.assertFalse(RootRestartGuard(self.root, lambda: self.now).start())
            self.assertEqual(json.loads(guards[3].path.read_text())['cooldown'], expected)
        self.assertEqual(len(list((self.root / 'runtime/dispatch/alerts').glob('*.json'))), 1)
        self.assertEqual(reset_resilience(self.root, 'operator', 'fixed root crash'), 0)
        self.assertTrue(RootRestartGuard(self.root, lambda: self.now).start())
        self.assertEqual(len(list((guards[3].path.parent / 'audit').glob('*.json'))), 1)

    def test_root_healthy_and_planned_stop_reset_budget(self):
        for _ in range(5):
            guard = RootRestartGuard(self.root, lambda: self.now)
            self.assertTrue(guard.start())
            guard.planned_stop()
        for _ in range(3):
            self.assertTrue(RootRestartGuard(self.root, lambda: self.now).start())
        guard.healthy()
        self.assertTrue(guard.start())

    def test_root_guard_run_refuses_with_78(self):
        for _ in range(3):
            self.assertTrue(RootRestartGuard(self.root).start())
        supervisor = LayerSupervisor(self.root, {'builder': [str(self.exe)]}, root_guard=True)
        with patch('orchestrator.layer_supervisor.register_supervisor_job') as register:
            self.assertEqual(supervisor.run(), 78)
            register.assert_not_called()

    def test_reset_commands_require_actor_and_reason_and_audit(self):
        from scripts import run_supervisor_layers, stop_supervisor
        with patch('sys.argv', ['run_supervisor_layers', '--reset-root-guard', '--state-root', str(self.root),
                                '--actor', 'operator', '--reason', 'fixed']):
            self.assertEqual(run_supervisor_layers.main(), 0)
        self.supervisor.save()
        with patch('sys.argv', ['stop_supervisor', '--reset-circuit', 'builder', '--state-root', str(self.root),
                                '--actor', 'operator', '--reason', 'fixed']):
            self.assertEqual(stop_supervisor.main(), 0)
        audits = [json.loads(p.read_text()) for p in (self.supervisor.path.parent / 'audit').glob('*.json')]
        self.assertEqual({a['operation'] for a in audits}, {'reset_root_guard', 'reset_circuit'})
        for module, args in ((run_supervisor_layers, ['--reset-root-guard']),
                             (stop_supervisor, ['--reset-circuit', 'builder'])):
            with patch('sys.argv', ['command', *args]), self.assertRaises(SystemExit) as raised:
                module.main()
            self.assertEqual(raised.exception.code, 2)

    def test_both_running_ten_minutes_clears_root_budget(self):
        supervisor = LayerSupervisor(self.root, {'builder': [str(self.exe)], 'claude': [str(self.exe)]},
                                     clock=lambda: self.now, root_guard=True)
        supervisor.guard_started = True
        for child in supervisor.children.values():
            child.status['state'] = 'running'
        with patch.object(supervisor, 'supervise_child'), patch.object(supervisor.root_guard, 'healthy') as healthy:
            supervisor.step()
            self.now = 599
            supervisor.step()
            healthy.assert_not_called()
            self.now = 600
            supervisor.step()
            healthy.assert_called_once()

    def test_policy_denial_stays_blocked_for_a_day(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            exe = root / 'python.exe'
            exe.write_bytes(b'blocked runtime')
            exc = OSError('policy denial')
            exc.winerror = 4551
            now = [0.0]
            with patch('orchestrator.layer_supervisor.owned_popen', side_effect=exc) as launch:
                supervisor = LayerSupervisor(root, {'builder': [str(exe)]}, clock=lambda: now[0])
                for second in range(0, 86401, 5):
                    now[0] = second
                    supervisor.step()
                self.assertEqual(launch.call_count, 1)
            child = supervisor.children['builder'].status
            self.assertEqual(child['state'], 'blocked_security_policy')
            self.assertTrue(child['circuit_open'])
            alerts = list((root / 'runtime/dispatch/alerts').glob('*.json'))
            self.assertEqual(len([p for p in alerts if json.loads(p.read_text()).get('layer')]), 1)


if __name__ == '__main__':
    unittest.main()
