"""Idle optimization contracts using disposable roots and fake clocks only."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dispatch.atomic_io import atomic_write_json
from orchestrator.idle_scan import fingerprint, ScanGate, write_status
from orchestrator.runtime_store import load_run_state
from orchestrator.supervisor import SupervisorConfig, process_once


class IdleEfficiencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_read_missing_run_does_not_create_directory(self):
        self.assertIsNone(load_run_state(self.root, 'missing'))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_snapshot_tracks_names_atomic_replace_and_in_place_edit(self):
        folder = self.root / 'queue'
        folder.mkdir()
        before = fingerprint([folder])
        path = folder / 'new.json'
        atomic_write_json(path, {'value': 1})
        added = fingerprint([folder])
        self.assertNotEqual(before, added)
        # Directory timestamps alone need not change on Windows for this edit.
        directory_mtime = folder.stat().st_mtime_ns
        path.write_text('{"value": 222}')
        os.utime(folder, ns=(directory_mtime, directory_mtime))
        edited = fingerprint([folder])
        self.assertNotEqual(added, edited)
        atomic_write_json(path, {'value': 3333})
        self.assertNotEqual(edited, fingerprint([folder]))
        path.unlink()
        self.assertEqual(before, fingerprint([folder]))

    def test_periodic_scan_cannot_miss_overdue_recovery(self):
        gate = ScanGate()
        self.assertTrue(gate.due(('same',), 0))
        gate.record(('same',), 0)
        self.assertFalse(gate.due(('same',), 59))
        self.assertTrue(gate.due(('same',), 60))
        self.assertTrue(gate.due(('changed',), 1))

    def test_status_changes_and_liveness(self):
        path = self.root / 'status.json'
        with patch('dispatch.atomic_io.atomic_write_json', wraps=atomic_write_json) as write:
            write_status(path, {'state': 'idle', 'tick': 0}, volatile={'tick'}, now=100)
            os.utime(path, (100, 100))
            write_status(path, {'state': 'idle', 'tick': 1}, volatile={'tick'}, now=129)
            self.assertEqual(write.call_count, 1)
            write_status(path, {'state': 'idle', 'tick': 2}, volatile={'tick'}, now=130)
            self.assertEqual(write.call_count, 2)
            write_status(path, {'state': 'failed', 'tick': 3}, volatile={'tick'}, now=130)
            self.assertEqual(write.call_count, 3)

    def test_paused_idle_ceiling_periodic_recovery_and_restart(self):
        cfg = SupervisorConfig()
        with patch('orchestrator.supervisor.recover_orphans') as recovery, patch(
                'orchestrator.supervisor.time.monotonic', return_value=0):
            process_once(self.root, config=cfg)
            recovery.assert_called_once()
        real_stat, real_scan = os.stat, os.scandir
        with patch('orchestrator.supervisor.recover_orphans') as recovery, patch(
                'orchestrator.supervisor.atomic_write_json') as write, patch(
                'dispatch.atomic_io.atomic_write_json') as status_write, patch(
                'os.stat', wraps=real_stat) as stat, patch(
                'os.scandir', wraps=real_scan) as scan, patch(
                'orchestrator.supervisor.time.monotonic', return_value=5):
            self.assertEqual(process_once(self.root, config=cfg)['status'], 'dispatch_paused')
            recovery.assert_not_called()
            write.assert_not_called()
            status_write.assert_not_called()
            self.assertLessEqual(stat.call_count + scan.call_count, 25)
        with patch('orchestrator.supervisor.recover_orphans') as recovery, patch(
                'orchestrator.supervisor.time.monotonic', return_value=60):
            process_once(self.root, config=cfg)
            recovery.assert_called_once()
        with patch('orchestrator.supervisor.recover_orphans') as recovery:
            process_once(self.root, config=SupervisorConfig())
            recovery.assert_called_once()

    def test_resumed_new_wake_is_processed_on_next_poll(self):
        from tests._dispatch_fixture import resume_builder_dispatch
        resume_builder_dispatch(self.root)
        cfg = SupervisorConfig()
        with patch('orchestrator.supervisor.reevaluate_blocked_builders', return_value=None), patch(
                'orchestrator.supervisor.process_wake_signal', return_value={'status': 'running', 'process_started': True}) as launch:
            process_once(self.root, config=cfg)
            launch.assert_not_called()
            atomic_write_json(self.root / 'runtime/dispatch/wake_queue/composer/new.json', {'assignment_id': 'synthetic'})
            self.assertTrue(process_once(self.root, config=cfg)['process_started'])
            launch.assert_called_once()

    def test_due_retry_checked_each_poll_using_cached_states(self):
        from tests._dispatch_fixture import resume_builder_dispatch
        resume_builder_dispatch(self.root)
        cfg = SupervisorConfig()
        from datetime import datetime, timezone
        from orchestrator.runtime_store import RunState
        state = RunState('synthetic', 'synthetic', 'synthetic', 'composer', 'composer-restricted',
                         process_state='blocked_quota', blocked_on='quota:grok',
                         next_eligible_at='2026-10-26T00:00:05Z')
        atomic_write_json(self.root / 'runtime/dispatch/runs/synthetic/supervisor_run.json', state.to_dict())
        cfg.condition_probe = lambda _: False
        with patch('orchestrator.builder_condition.dispatch_condition_retry', return_value={
                'status': 'running', 'process_started': True}) as launch:
            cfg.now = lambda: datetime(2026, 10, 26, tzinfo=timezone.utc)
            process_once(self.root, config=cfg)
            launch.assert_not_called()
            cfg.now = lambda: datetime(2026, 10, 26, 0, 0, 5, tzinfo=timezone.utc)
            self.assertTrue(process_once(self.root, config=cfg)['process_started'])
            launch.assert_called_once()

    def test_active_run_retains_per_poll_failure_detection(self):
        from orchestrator.runtime_store import RunState
        state = RunState('active', 'active', 'active', 'composer', 'composer-restricted',
                         process_state='running', pid=123, process_start_time='synthetic')
        atomic_write_json(self.root / 'runtime/dispatch/runs/active/supervisor_run.json', state.to_dict())
        cfg = SupervisorConfig()
        with patch('orchestrator.supervisor.recover_orphans') as recovery:
            process_once(self.root, config=cfg)
            process_once(self.root, config=cfg)
            self.assertEqual(recovery.call_count, 2)

    def test_idle_consumer_picks_up_new_event_next_poll(self):
        from orchestrator.claude_event_consumer import ClaudeEventConsumer
        from dispatch.orchestrator_pokes import write_orchestrator_poke
        consumer = ClaudeEventConsumer(self.root, processor=lambda **kw: {
            'status': 'completed', 'pid': 123, 'verdict': 'accepted', 'session_id': 'synthetic'})
        with patch('orchestrator.consumer_claims.process_start_time', return_value='synthetic'):
            self.assertEqual(consumer.process_once()['status'], 'idle')
            with patch.object(consumer, '_process_once', wraps=consumer._process_once) as full:
                consumer.process_once()
                full.assert_not_called()
                write_orchestrator_poke(self.root, source='composer', assignment_id='synthetic',
                                        task_id='synthetic', event='assignment_completed')
                result = consumer.process_once()
                full.assert_called_once()
                self.assertEqual(result['status'], 'resolved')

    def test_realistic_idle_fixture_filesystem_ceiling(self):
        from orchestrator.runtime_store import RunState
        template = json.loads((Path(__file__).parent / 'fixtures/r12_stuck/inbox.json').read_text())
        for i in range(15):
            record = dict(template, assignment_id=f'fixture-{i}', status='reviewable_failure')
            atomic_write_json(self.root / f'runtime/dispatch/assignments/inbox/fixture-{i}.json', record)
        for i in range(27):
            state = RunState(f'fixture-{i}', f'fixture-{i % 15}', 'fixture', 'composer',
                             'composer-restricted', process_state='completed')
            atomic_write_json(self.root / f'runtime/dispatch/runs/fixture-{i}/supervisor_run.json', state.to_dict())
        cfg = SupervisorConfig()
        process_once(self.root, config=cfg)
        with patch('os.stat', wraps=os.stat) as stat, patch('os.scandir', wraps=os.scandir) as scan, patch(
                'io.open', wraps=__import__('io').open) as opened, patch(
                'dispatch.atomic_io.atomic_write_json') as write, patch(
                'orchestrator.runtime_store.load_run_state') as load:
            process_once(self.root, config=cfg)
            self.assertLessEqual(stat.call_count + scan.call_count + opened.call_count, 65)
            write.assert_not_called()
            load.assert_not_called()


if __name__ == '__main__':
    unittest.main()
