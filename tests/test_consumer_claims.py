"""Offline recovery and fairness regressions; no providers or OS signals."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from dispatch.atomic_io import atomic_write_json
from dispatch.orchestrator_pokes import write_orchestrator_poke
from orchestrator.claude_event_consumer import ClaudeEventConsumer, event_fingerprint, load_watcher_status


class FairnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / 'runtime/dispatch/claude_event_consumer'
        self.head, _ = write_orchestrator_poke(self.root, source='composer', assignment_id='old',
                                            task_id='T-old', event='assignment_completed')
        path = self.root / self.head['source_path']
        self.head['created_at'] = '2026-08-14T15:56:09Z'
        atomic_write_json(path, self.head)
        older = path.with_name('2026-08-14-head.json')
        path.rename(older)
        self.head['source_path'] = older.relative_to(self.root).as_posix()
        self.fp = event_fingerprint(self.head)
        self.claim = self.base / 'claims' / (self.fp + '.json')
        self.calls = []
        self.events = []
        self.consumer = ClaudeEventConsumer(self.root, processor=self.process,
            condition_probe=lambda _: False, state_logger=self.events.append)

    def process(self, **kw):
        self.calls.append(kw['assignment_id'])
        return dict(status='completed', pid=4242, verdict='accepted')

    def newer(self):
        write_orchestrator_poke(self.root, source='composer', assignment_id='new',
                                task_id='T-new', event='assignment_completed')

    def legacy(self, **extra):
        atomic_write_json(self.claim, dict(fingerprint=self.fp, assignment_id='old',
                          claimed_at='2026-08-14T15:56:09Z', **extra))

    def test_legacy_head_skipped_and_alerted(self):
        self.legacy()
        self.newer()
        self.consumer.process_once()
        self.assertEqual(self.calls, ['new'])
        self.assertTrue(self.claim.exists())
        status = load_watcher_status(self.root)
        self.assertTrue(status['stale_claim_alert_active'])
        self.assertEqual(status['stale_claims'][0]['fingerprint'], self.fp)
        self.assertEqual(status['stale_claims'][0]['assignment_id'], 'old')
        self.assertGreater(status['stale_claims'][0]['age_seconds'], 0)

    def test_auth_deferred_head_skipped(self):
        now = datetime.now(timezone.utc)
        deferred = dict(fingerprint=self.fp, blocked_on='auth:claude',
            deferred_since=now.isoformat(), next_eligible_at=(now + timedelta(hours=1)).isoformat(),
            last_probe_at=now.isoformat(), attempt_count=1)
        atomic_write_json(self.base / 'deferred' / (self.fp + '.json'), deferred)
        self.newer()
        self.consumer.process_once()
        self.assertEqual(self.calls, ['new'])
        self.assertEqual(json.loads((self.base / 'deferred' / (self.fp + '.json')).read_text()), deferred)

    def test_restart_clears_dead_lifecycle(self):
        self.legacy()
        atomic_write_json(self.base / 'status.json', dict(lifecycle_state='review_starting', pid=None))
        self.consumer.process_once()
        self.assertEqual(load_watcher_status(self.root)['lifecycle_state'], 'blocked_stale_claim')

    def test_dead_owner_recovered_once(self):
        self.legacy(consumer_pid=111, consumer_start_time='old', consumer_token='dead',
                    review_pid=222, review_start_time='child')
        with patch('orchestrator.consumer_claims.process_liveness', return_value=False):
            self.consumer.process_once()
            self.consumer.process_once()
        self.assertEqual(self.calls, ['old'])
        recovered = [e for e in self.events if e['event'] == 'claim_recovered']
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]['prior_owner']['consumer_token'], 'dead')
        self.assertEqual(len(list((self.base / 'audit').glob('*.json'))), 1)

    def test_live_or_unknown_owner_or_child_preserved(self):
        for owner, child in [(True, False), (None, False), (False, True), (False, None)]:
            with self.subTest(owner=owner, child=child):
                self.legacy(consumer_pid=111, consumer_start_time='old', consumer_token='dead',
                            review_pid=222, review_start_time='child')
                before = self.claim.read_bytes()
                with patch('orchestrator.consumer_claims.process_liveness', side_effect=[owner, child]):
                    self.consumer.process_once()
                self.assertEqual(self.claim.read_bytes(), before)
        self.assertEqual(self.calls, [])

    def test_claim_identity_available_during_processor_and_child_callback(self):
        def processor(**kw):
            claim = json.loads(self.claim.read_text())
            self.assertIsInstance(claim['consumer_pid'], int)
            self.assertTrue(claim['consumer_start_time'])
            self.assertTrue(claim['consumer_token'])
            kw['on_review_started'](4242, 'child-start')
            claim = json.loads(self.claim.read_text())
            self.assertEqual((claim['review_pid'], claim['review_start_time']), (4242, 'child-start'))
            return dict(status='completed', pid=4242, process_start_time='child-start', verdict='accepted')
        self.consumer.processor = processor
        self.assertEqual(self.consumer.process_once()['status'], 'resolved')

    def test_resolved_deferred_head_is_archived_and_next_runs(self):
        now = datetime.now(timezone.utc)
        atomic_write_json(self.base / 'resolved' / (self.fp + '.json'), dict(verdict='accepted'))
        atomic_write_json(self.base / 'deferred' / (self.fp + '.json'), dict(
            fingerprint=self.fp, deferred_since=now.isoformat(),
            next_eligible_at=(now + timedelta(hours=1)).isoformat(), blocked_on='auth:claude'))
        self.newer()
        self.consumer.process_once()
        self.assertEqual(self.calls, ['new'])
        self.assertFalse((self.root / self.head['source_path']).exists())

    def test_empty_tick_clears_previous_running_status(self):
        (self.root / self.head['source_path']).unlink()
        atomic_write_json(self.base / 'status.json', dict(lifecycle_state='review_running', pid=4242))
        self.consumer.process_once()
        status = load_watcher_status(self.root)
        self.assertEqual(status['lifecycle_state'], 'idle')
        self.assertIsNone(status['pid'])

    def test_competing_consumer_does_not_launch_owned_fingerprint(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        started, proceed = Event(), Event()

        def blocking(**kw):
            started.set()
            self.assertTrue(proceed.wait(10))
            return self.process(**kw)

        first = ClaudeEventConsumer(self.root, processor=blocking)
        with ThreadPoolExecutor(max_workers=1) as pool:
            running = pool.submit(first.process_once)
            try:
                self.assertTrue(started.wait(10))
                self.assertEqual(self.consumer.process_once()['status'], 'deferred')
                self.assertEqual(self.calls, [])
            finally:
                proceed.set()
            self.assertEqual(running.result(timeout=10)['status'], 'resolved')
        self.assertEqual(self.calls, ['old'])

    def test_a_tick_never_launches_a_second_child_after_pid_is_known(self):
        calls = []
        self.consumer.processor = lambda **kw: calls.append(kw) or dict(
            status='failed_launch', pid=4242, blocked_reason='no genuine activity')
        self.consumer.process_once()
        self.assertEqual(len(calls), 1)


class OperatorTests(unittest.TestCase):
    setUp = FairnessTests.setUp
    process = FairnessTests.process
    legacy = FairnessTests.legacy
    def test_release_legacy_claim_audits_actor_reason(self):
        from orchestrator.consumer_claims import release
        self.legacy()
        record = release(self.root, self.fp, actor='operator', reason='confirmed abandoned')
        self.assertFalse(self.claim.exists())
        self.assertEqual(record['event'], 'claim_released')
        self.assertEqual(record['actor'], 'operator')
        self.assertEqual(record['reason'], 'confirmed abandoned')
        self.assertEqual(record['prior_owner']['assignment_id'], 'old')

    def test_operator_refuses_resolved_live_unknown_and_empty_audit(self):
        from orchestrator.consumer_claims import release
        self.legacy(consumer_pid=111, consumer_start_time='start', consumer_token='owner')
        for alive in (True, None):
            with patch('orchestrator.consumer_claims.process_liveness', return_value=alive):
                with self.assertRaisesRegex(ValueError, 'live or unknown'):
                    release(self.root, self.fp, actor='op', reason='abandoned')
        self.legacy()
        atomic_write_json(self.base / 'resolved' / (self.fp + '.json'), {'verdict': 'accepted'})
        with self.assertRaisesRegex(ValueError, 'resolved'):
            release(self.root, self.fp, actor='op', reason='abandoned')
        with self.assertRaisesRegex(ValueError, 'actor and reason'):
            release(self.root, self.fp, actor='', reason='')
        self.assertTrue(self.claim.exists())
        self.assertFalse(list((self.base / 'audit').glob('*.json')))

    def test_lease_release_checks_run_pid_and_audits(self):
        from orchestrator.consumer_claims import release, list_records
        lease = self.root / 'runtime/dispatch/supervisor_leases/review-old.json'
        atomic_write_json(lease, dict(review_run_id='review-run', holder='claude-reviewer'))
        atomic_write_json(self.root / 'runtime/dispatch/reviews/review-run/review_run.json',
                          dict(pid=333, process_start_time='review-start'))
        self.assertEqual(list_records(self.root)['leases'][0]['key'], 'review-old')
        for alive in (True, None):
            with patch('orchestrator.consumer_claims.process_liveness', return_value=alive):
                with self.assertRaisesRegex(ValueError, 'live or unknown'):
                    release(self.root, 'review-old', kind='lease', actor='op', reason='abandoned')
        with patch('orchestrator.consumer_claims.process_liveness', return_value=False):
            record = release(self.root, 'review-old', kind='lease', actor='op', reason='abandoned')
        self.assertFalse(lease.exists())
        self.assertEqual(record['event'], 'lease_released')

    def test_claim_release_checks_matching_lease_child(self):
        from orchestrator.consumer_claims import release
        self.legacy()
        atomic_write_json(self.root / 'runtime/dispatch/supervisor_leases/review-old.json',
                          dict(review_pid=333, review_start_time='start'))
        with patch('orchestrator.consumer_claims.process_liveness', return_value=True):
            with self.assertRaisesRegex(ValueError, 'live or unknown'):
                release(self.root, self.fp, actor='op', reason='abandoned')

    def test_resolved_lease_and_blank_reason_are_refused(self):
        from orchestrator.consumer_claims import release
        lease = self.root / 'runtime/dispatch/supervisor_leases/review-old.json'
        atomic_write_json(lease, dict(review_run_id='review-run'))
        with self.assertRaisesRegex(ValueError, 'actor and reason'):
            release(self.root, 'review-old', kind='lease', actor='op', reason=' ')
        atomic_write_json(self.base / 'resolved' / (self.fp + '.json'), dict(assignment_id='old'))
        with self.assertRaisesRegex(ValueError, 'resolved'):
            release(self.root, 'review-old', kind='lease', actor='op', reason='abandoned')
        self.assertTrue(lease.exists())

    def test_new_claim_with_incomplete_identity_is_not_operator_released(self):
        from orchestrator.consumer_claims import release
        self.legacy(consumer_token='owner', consumer_pid=None)
        with self.assertRaisesRegex(ValueError, 'live or unknown'):
            release(self.root, self.fp, actor='op', reason='abandoned')

    def test_cli_list_release_and_bad_key(self):
        from scripts.consumer_claims import main
        from contextlib import redirect_stdout, redirect_stderr
        from io import StringIO
        self.legacy()
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['--root', str(self.root), 'list']), 0)
        self.assertEqual(json.loads(output.getvalue())['claims'][0]['key'], self.fp)
        with redirect_stderr(StringIO()):
            self.assertEqual(main(['--root', str(self.root), 'release', '../escape',
                                   '--actor', 'op', '--reason', 'abandoned']), 1)
        with redirect_stdout(StringIO()):
            self.assertEqual(main(['--root', str(self.root), 'release', self.fp,
                                   '--actor', 'op', '--reason', 'abandoned']), 0)


class LivenessTests(unittest.TestCase):
    def test_current_identity_and_pid_reuse(self):
        import os
        from orchestrator.consumer_claims import process_liveness
        from orchestrator.process_ownership import process_start_time
        start = process_start_time(os.getpid())
        self.assertTrue(start)
        self.assertTrue(process_liveness(os.getpid(), start))
        self.assertFalse(process_liveness(os.getpid(), 'different-start'))
        self.assertIsNone(process_liveness(os.getpid(), None))

    def test_invalid_and_inaccessible_identity_is_unknown(self):
        from orchestrator.consumer_claims import process_liveness
        for pid, start in [(0, 'start'), (True, 'start'), (111, {}), (2**70, 'start')]:
            self.assertIsNone(process_liveness(pid, start))
        with patch('orchestrator.consumer_claims.process_start_time', side_effect=OSError('denied')):
            self.assertIsNone(process_liveness(111, 'start'))

    def test_child_exit_does_not_erase_recorded_creation_time(self):
        from orchestrator.consumer_claims import acquire, update_child, directory, finish
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fp = 'a' * 64
            acquire(root, fp, dict(consumer_token='token'))
            update_child(root, fp, 'token', 111, 'known-start')
            update_child(root, fp, 'token', 111, None)
            path = directory(root) / 'claims' / (fp + '.json')
            self.assertEqual(json.loads(path.read_text())['review_start_time'], 'known-start')
            with self.assertRaisesRegex(ValueError, 'ownership changed'):
                update_child(root, fp, 'other', 222, 'different')
            finish(root, fp, 'other')
            self.assertTrue(path.exists())


if __name__ == '__main__':
    unittest.main()
