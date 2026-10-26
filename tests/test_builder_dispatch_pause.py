import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from dispatch.atomic_io import atomic_write_json
from orchestrator.builder_dispatch import dispatch_status
from orchestrator.supervisor import SupervisorConfig, process_once, process_wake_signal, _launch_agent_process
from scripts.stop_supervisor import builder_dispatch, main


class DispatchPauseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'AGENTIC_BUILDER_RUN_ID': ''})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_pause_keeps_wake_and_skips_due_retry_then_resume(self):
        wake = self.root / 'runtime/dispatch/wake_queue/composer/pending.json'
        atomic_write_json(wake, {'assignment_id': 'pending', 'retry': {'attempts': 3}})
        before = wake.read_bytes()
        self.assertEqual(builder_dispatch(self.root, 'pause', 'owner', 'checks pending'), 0)
        with patch('orchestrator.supervisor.reevaluate_blocked_builders') as retry, patch(
                'orchestrator.supervisor.process_wake_signal') as launch:
            self.assertEqual(process_once(self.root)['status'], 'dispatch_paused')
            retry.assert_not_called()
            launch.assert_not_called()
            self.assertEqual(wake.read_bytes(), before)
            self.assertEqual(builder_dispatch(self.root, 'resume', 'owner', 'checks passed'), 0)
            retry.return_value = {'status': 'running', 'process_started': True}
            self.assertTrue(process_once(self.root)['process_started'])
            retry.assert_called_once()
        status = json.loads((self.root / 'runtime/dispatch/supervisor_status.json').read_text())
        self.assertFalse(status['builder_dispatch']['paused'])
        audits = list((self.root / 'runtime/dispatch/layer_supervisor/audit').glob('*.json'))
        self.assertEqual(len(audits), 2)
        for path in audits:
            self.assertEqual(json.loads(path.read_text())['exit_code'], 0)

    def test_invalid_and_absent_fail_closed(self):
        self.assertTrue(dispatch_status(self.root)['paused'])
        self.assertEqual(dispatch_status(self.root)['reason'], 'no control state (fail closed)')
        self.assertFalse((self.root/'runtime/dispatch/alerts').exists())
        path = self.root / 'runtime/dispatch/layer_supervisor/control/builder_dispatch.json'
        path.parent.mkdir(parents=True)
        for content in ['{', '[]', '{"paused": false}', '{"paused": "false"}']:
            path.write_text(content)
            self.assertTrue(dispatch_status(self.root)['paused'])
            self.assertEqual(process_once(self.root)['status'], 'dispatch_paused')
        self.assertEqual(len(list((self.root / 'runtime/dispatch/alerts').glob('*.json'))), 1)
        path.unlink()
        self.assertEqual(process_once(self.root)['status'], 'dispatch_paused')

    def test_cli_and_builder_guard(self):
        for operation in ['pause', 'resume']:
            with patch('sys.argv', ['stop_supervisor.py', '--state-root', str(self.root),
                       '--builder-dispatch', operation, '--actor', 'owner', '--reason', 'checks']), patch(
                       'scripts.stop_supervisor.resolve_state_root', return_value=self.root):
                self.assertEqual(main(), 0)
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.dict(os.environ, {'AGENTIC_BUILDER_RUN_ID': 'fixture'}):
            self.assertEqual(main(), 3)
            self.assertEqual(builder_dispatch(self.root, 'pause', 'builder', 'forbidden'), 3)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_continuation_and_fallback_spawn_guard(self):
        builder_dispatch(self.root, 'pause', 'owner', 'checks')
        # The public wake wrapper must stop before reading or claiming anything.
        self.assertEqual(process_wake_signal(self.root, self.root / 'missing.json', config=SupervisorConfig())['status'], 'dispatch_paused')
        popen = Mock()
        with patch('orchestrator.supervisor._classify_launch_denial'):
            plan = Mock()
            plan.argv = ['fake']
            with patch('orchestrator.supervisor.launch_process') as launch:
                result = _launch_agent_process(self.root, Mock(), plan, stdout_path=None, stderr_path=None, popen=popen)
                self.assertIn('dispatch_paused', result[1])
                launch.assert_not_called()
        popen.assert_not_called()

    def test_paused_tick_finalizes_r12_fixture(self):
        from tests.test_stuck_assignment_recovery import StuckAssignmentTests
        fixture = StuckAssignmentTests('test_sweep_once_and_idle_no_writes')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        builder_dispatch(fixture.root, 'pause', 'owner', 'checks')
        with patch('orchestrator.supervisor.recover_orphans') as recover:
            self.assertEqual(process_once(fixture.root)['status'], 'dispatch_paused')
            recover.assert_called_once()
        self.assertEqual(fixture.status(), 'reviewable_failure')
        self.assertEqual(len(fixture.notices()), 1)

    def test_low_level_manual_and_legacy_launches_are_noops(self):
        from orchestrator.agent_launcher import LaunchPlan, launch_process
        from orchestrator.builder_condition import dispatch_condition_retry, reevaluate_blocked_builders
        from dispatch.local_builder_core import run_adapter_local_builder
        with patch('orchestrator.process_ownership.owned_popen') as spawn:
            for agent in ('composer', 'codex', 'acceptance'):
                plan = LaunchPlan(agent, 'fake', ['fake'], str(self.root), 'fake')
                handle, reason = launch_process(plan, stdout_path=self.root / 'out', stderr_path=self.root / 'err')
                self.assertIsNone(handle)
                self.assertIn('dispatch_paused', reason)
            source = Mock()
            launch = Mock()
            self.assertEqual(dispatch_condition_retry(self.root, source, config=Mock(), launch=launch)['status'], 'dispatch_paused')
            self.assertEqual(reevaluate_blocked_builders(self.root, config=Mock(), launch=launch)['status'], 'dispatch_paused')
            source.assert_not_called()
            launch.assert_not_called()
            hook = Mock()
            result = run_adapter_local_builder(
                self.root, task_path=self.root / 'missing.yaml', adapter={}, config=Mock(),
                evaluate_gates=hook, build_command_plan=hook, prepare_environment=hook,
                resolve_executable=hook)
            self.assertIn('dispatch_paused', result.blocked_reasons[0])
            hook.assert_not_called()
            spawn.assert_not_called()

    def test_review_consumer_continues_while_paused(self):
        from dispatch.orchestrator_pokes import write_orchestrator_poke
        from orchestrator.claude_event_consumer import ClaudeEventConsumer
        builder_dispatch(self.root, 'pause', 'owner', 'checks')
        write_orchestrator_poke(self.root, source='composer', assignment_id='fixture',
                                task_id='T-fixture', event='assignment_completed')
        reviewer = Mock(return_value={'status': 'completed', 'pid': 42,
                                     'session_id': 'fake', 'verdict': 'accepted'})
        with patch('orchestrator.process_ownership.owned_popen') as spawn:
            self.assertEqual(ClaudeEventConsumer(self.root, processor=reviewer).process_once()['status'], 'resolved')
            reviewer.assert_called_once()
            spawn.assert_not_called()

    def test_restart_and_layer_telemetry(self):
        from orchestrator.layer_supervisor import LayerSupervisor
        builder_dispatch(self.root, 'pause', 'owner', 'checks')
        for _ in range(2):
            supervisor = LayerSupervisor(self.root, {})
            supervisor.save()
            self.assertEqual(process_once(self.root)['status'], 'dispatch_paused')
        status = json.loads((self.root / 'runtime/dispatch/layer_supervisor/status.json').read_text())
        self.assertEqual(status['builder_dispatch']['reason'], 'checks')
        self.assertTrue(status['builder_dispatch']['paused'])

    def test_lowest_launcher_and_legacy_worker_are_noops(self):
        from orchestrator.agent_launcher import LaunchPlan, launch_process
        from dispatch.local_builder_core import run_adapter_local_builder
        from scripts.run_local_builder_worker import process_one
        from scripts.watch_assignments import process_one as watch_one
        builder_dispatch(self.root, 'pause', 'owner', 'checks')
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        popen = Mock()
        for agent in ['composer', 'codex', 'acceptance']:
            plan = LaunchPlan(agent, 'fixture', ['fake'], str(self.root), 'fake')
            handle, reason = launch_process(plan, stdout_path=self.root/'out',
                                            stderr_path=self.root/'err', popen=popen)
            self.assertIsNone(handle)
            self.assertIn('dispatch_paused', reason)
        with patch('dispatch.local_builder_core.launch_process') as launch:
            result = run_adapter_local_builder(
                self.root, task_path=self.root/'missing.yaml', adapter={}, config=Mock(),
                evaluate_gates=Mock(), build_command_plan=Mock(),
                prepare_environment=Mock(), resolve_executable=Mock())
            self.assertIn('dispatch_paused', result.blocked_reasons[0])
            self.assertEqual(process_one(self.root)['status'], 'dispatch_paused')
            self.assertEqual(watch_one(self.root, 'composer')['status'], 'dispatch_paused')
            launch.assert_not_called()
        popen.assert_not_called()
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_restart_status_and_claude_launch_exemption(self):
        from orchestrator.agent_launcher import LaunchPlan, launch_process
        from orchestrator.layer_supervisor import LayerSupervisor
        builder_dispatch(self.root, 'pause', 'owner', 'checks')
        for _ in range(2):
            supervisor = LayerSupervisor(self.root, {}, popen=Mock())
            supervisor.save()
            status = json.loads((self.root/'runtime/dispatch/layer_supervisor/status.json').read_text())
            self.assertEqual(status['builder_dispatch'], dispatch_status(self.root))
            self.assertTrue(status['builder_dispatch']['paused'])
            self.assertEqual(process_once(self.root)['status'], 'dispatch_paused')
        popen = Mock(return_value=Mock(pid=12345))
        plan = LaunchPlan('claude-reviewer', 'fixture', ['fake'], str(self.root), 'fake')
        with patch('orchestrator.process_ownership.owned_popen', popen):
            handle, _ = launch_process(plan, stdout_path=self.root/'out', stderr_path=self.root/'err')
        self.assertIsNotNone(handle)
        popen.assert_called_once()

    def test_r12_notice_preserved_and_claude_review_processed_while_paused(self):
        from tests.test_stuck_assignment_recovery import StuckAssignmentTests
        from orchestrator.claude_event_consumer import ClaudeEventConsumer
        fixture = StuckAssignmentTests('test_sweep_once_and_idle_no_writes')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        builder_dispatch(fixture.root, 'pause', 'owner', 'checks')
        with patch('orchestrator.supervisor.launch_process') as launch:
            for _ in range(2):
                self.assertEqual(process_once(fixture.root)['status'], 'dispatch_paused')
            launch.assert_not_called()
        self.assertEqual(fixture.status(), 'reviewable_failure')
        self.assertEqual(len(fixture.notices()), 1)
        reviewer = Mock(return_value={'status': 'completed', 'pid': 42,
                                      'verdict': 'changes_requested', 'session_id': 'fixture'})
        consumer = ClaudeEventConsumer(fixture.root, processor=reviewer)
        # Failure notices retain the consumer's existing notice-only behavior.
        self.assertEqual(consumer.process_once()['status'], 'idle')
        from dispatch.orchestrator_pokes import write_orchestrator_poke
        _, errors = write_orchestrator_poke(fixture.root, source='composer',
            assignment_id='review-fixture', task_id='T-REVIEW', event='assignment_completed')
        self.assertEqual(errors, [])
        self.assertEqual(consumer.process_once()['status'], 'resolved')
        reviewer.assert_called_once()
        self.assertTrue(dispatch_status(fixture.root)['paused'])

    def test_unreadable_control_is_deduplicated(self):
        path = self.root/'runtime/dispatch/layer_supervisor/control/builder_dispatch.json'
        original = Path.read_text
        def read(target, *args, **kwargs):
            if target == path:
                raise PermissionError('fixture denied')
            return original(target, *args, **kwargs)
        with patch.object(Path, 'read_text', read):
            self.assertTrue(dispatch_status(self.root)['paused'])
            self.assertTrue(dispatch_status(self.root)['paused'])
        self.assertEqual(len(list((self.root/'runtime/dispatch/alerts').glob('*.json'))), 1)


from tests.test_builder_condition_retry import ConditionRetryFixture, _monitor


class DispatchPauseIntegrationTests(ConditionRetryFixture):
    def test_due_retry_and_pending_wake_preserved_until_resume(self):
        import sys
        with patch.dict(os.environ, {}):
            cfg = self._config(grok_executable=sys.executable)
            kwargs = dict(config=cfg, popen=self._popen, launch_plan_builder=self._plan,
                          monitor=_monitor('quota exceeded'))
            first = process_once(self.root, **kwargs)
            self.assertEqual(first.get('process_state'), 'blocked_quota', first)
            self.clock.advance(minutes=16)
            self._write_wake()
            before = self.wake_path.read_bytes()
            blocked = self._runs()[0].to_dict()
            builder_dispatch(self.root, 'pause', 'owner', 'checks pending')
            with patch('orchestrator.supervisor.launch_process') as launch:
                for _ in range(2):
                    self.assertEqual(process_once(self.root, **kwargs)['status'], 'dispatch_paused')
                launch.assert_not_called()
            self.assertEqual(self.wake_path.read_bytes(), before)
            self.assertEqual(self._runs()[0].to_dict(), blocked)
            builder_dispatch(self.root, 'resume', 'owner', 'checks passed')
            report = process_once(self.root, **kwargs)
            self.assertTrue(report['process_started'], report)
            self.assertEqual(len(self._runs()), 2)

    def test_pending_wake_launches_next_tick_after_resume(self):
        import sys
        with patch.dict(os.environ, {}):
            kwargs = dict(config=self._config(grok_executable=sys.executable), popen=self._popen,
                          launch_plan_builder=self._plan, monitor=_monitor('', exit_code=0))
            before = self.wake_path.read_bytes()
            builder_dispatch(self.root, 'pause', 'owner', 'checks')
            self.assertEqual(process_once(self.root, **kwargs)['status'], 'dispatch_paused')
            self.assertEqual(self.wake_path.read_bytes(), before)
            builder_dispatch(self.root, 'resume', 'owner', 'checks passed')
            report = process_once(self.root, **kwargs)
            self.assertTrue(report['process_started'], report)

    def test_direct_condition_retry_and_continuation_no_mutation(self):
        from orchestrator.builder_condition import dispatch_condition_retry, reevaluate_blocked_builders
        builder_dispatch(self.root, 'pause', 'owner', 'checks')
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        source = Mock(attempts=2)
        launch = Mock()
        self.assertEqual(dispatch_condition_retry(self.root, source, config=self._config(),
                                                  launch=launch)['status'], 'dispatch_paused')
        self.assertEqual(reevaluate_blocked_builders(self.root, config=self._config(),
                                                     launch=launch)['status'], 'dispatch_paused')
        with patch('orchestrator.supervisor.launch_process') as physical:
            self.assertEqual(process_wake_signal(self.root, self.wake_path, config=self._config(),
                                                condition_retry_from=source)['status'], 'dispatch_paused')
            physical.assert_not_called()
        launch.assert_not_called()
        self.assertEqual(source.attempts, 2)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_orphan_finalizes_without_launch_while_paused(self):
        from orchestrator.runtime_store import save_run_state
        from dispatch.assignment_channel import read_assignment
        import sys
        cfg = self._config(grok_executable=sys.executable)
        process_once(self.root, config=cfg, popen=self._popen, launch_plan_builder=self._plan,
                     monitor=_monitor('quota exceeded'))
        state = self._runs()[0]
        state.process_state = 'running'
        state.pid = 4242
        (self.root/state.stdout_path).write_text('{"type":"max_turns_reached"}\n{"type":"end","stopReason":"cancelled"}\n')
        save_run_state(self.root, state)
        builder_dispatch(self.root, 'pause', 'owner', 'checks')
        with patch('orchestrator.supervisor.pid_is_alive', return_value=False), patch(
                'orchestrator.supervisor.launch_process') as launch:
            for _ in range(2):
                self.assertEqual(process_once(self.root, config=cfg)['status'], 'dispatch_paused')
            launch.assert_not_called()
        self.assertEqual(read_assignment(self.root, self.assignment_id)[0].status, 'reviewable_failure')
        self.assertEqual(len(list((self.root/'runtime/dispatch/completion_notices').glob('*.json'))), 1)


    def test_same_assignment_continuation_preserves_state(self):
        from tests.test_retry_lock_continuation import RetryLockContinuationTests
        fixture = RetryLockContinuationTests('test_transient_continues_then_success_holds_for_review')
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.transient()
        builder_dispatch(fixture.root, 'pause', 'owner', 'checks')
        before = {p: p.read_bytes() for p in fixture.root.rglob('*') if p.is_file()}
        popen = Mock()
        with patch('orchestrator.supervisor.launch_process') as launch:
            result = process_wake_signal(fixture.root, fixture.wake_path,
                config=fixture._config(), popen=popen, launch_plan_builder=fixture._plan)
            self.assertEqual(result['status'], 'dispatch_paused')
            launch.assert_not_called()
        popen.assert_not_called()
        self.assertEqual(before, {p: p.read_bytes() for p in fixture.root.rglob('*') if p.is_file()})
