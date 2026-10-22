"""Offline deploy-layout regressions for abandoned review capacity."""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from dispatch.atomic_io import atomic_write_json
from orchestrator import consumer_claims, review_dispatcher as dispatcher
from orchestrator.claude_event_consumer import ClaudeEventConsumer, event_fingerprint, load_watcher_status
from orchestrator.claude_reviewer_adapter import ClaudeReviewerAdapter
from tests import test_claude_reviewer_adapter as fixture


class ReviewLeaseRecoveryTests(unittest.TestCase):
    setUp = fixture.ReviewFlowFixture.setUp
    tearDown = fixture.ReviewFlowFixture.tearDown

    def prepare(self):
        self.addCleanup(patch.stopall)
        patch('orchestrator.review_dispatcher._git', return_value='a' * 40).start()
        self.launches = []
        self.events = []
        self.clock = datetime(2026, 10, 22, tzinfo=timezone.utc)

        def popen(argv, **kwargs):
            self.launches.append(argv)
            kwargs['stdout'].write(json.dumps(dict(type='result', result=json.dumps(fixture._valid_verdict()),
                                                  session_id='recovered-session')))
            kwargs['stdout'].flush()
            return fixture.FakeProcess(pid=9090, exit_code=0)

        adapter = ClaudeReviewerAdapter(self.root, claude_executable=sys.executable, popen=popen)
        self.consumer = ClaudeEventConsumer(self.root, now=lambda: self.clock,
            state_logger=self.events.append, condition_probe=lambda _: False,
            processor=lambda **kw: dispatcher.process_one_review(self.root,
                assignment_id=kw['assignment_id'], adapter=adapter,
                on_review_started=kw['on_review_started']))
        # Completion already emits the poke; use its stable identity.
        from dispatch.orchestrator_pokes import list_orchestrator_pokes
        pokes, _ = list_orchestrator_pokes(self.root)
        self.poke = next(p for p in pokes if p['event'] == 'assignment_completed')
        self.fp = event_fingerprint(self.poke)
        self.lease = dispatcher.review_lease_path(self.root, self.assignment_id)

    def abandoned(self, **extra):
        request, errors = dispatcher.create_review_request(self.root, self.assignment_id)
        self.assertEqual(errors, [])
        prior = dict(assignment_id=self.assignment_id, review_run_id=request['review_run_id'],
                     consumer_pid=111, consumer_start_time='old-owner', consumer_token='dead',
                     acquired_at='2026-08-14T15:56:09Z', **extra)
        atomic_write_json(self.lease, prior)
        return prior

    def test_legacy_missing_identity_release_finalizes_and_unblocks_capacity(self):
        self.prepare()
        prior = self.abandoned()
        prior.pop('consumer_token')
        prior.pop('consumer_pid')
        prior.pop('consumer_start_time')
        atomic_write_json(self.lease, prior)
        run_dir = self.root / 'runtime/dispatch/reviews' / prior['review_run_id']
        state_path = run_dir / 'review_run.json'
        atomic_write_json(state_path, dict(pid=35728, process_start_time=None,
            process_state='running', started_at='2026-08-14T15:56:10Z'))
        original = state_path.read_bytes()
        (run_dir / 'stdout.log').write_bytes(b'legacy output')
        claim = consumer_claims.directory(self.root) / 'claims' / f'{self.fp}.json'
        atomic_write_json(claim, dict(assignment_id=self.assignment_id))
        with patch('orchestrator.consumer_claims.process_start_time', return_value=None), patch(
                'orchestrator.consumer_claims.os.name', 'nt'), patch(
                'orchestrator.process_ownership.kernel.OpenProcess', return_value=0), patch(
                'orchestrator.consumer_claims.ctypes.get_last_error', return_value=87):
            self.assertIsNone(consumer_claims.recovery_reason(self.root, prior))
            # Claim must evaluate the matching lease's own review-run evidence.
            consumer_claims.release(self.root, self.fp, actor='operator', reason='legacy dead')
            state = consumer_claims.read_record(state_path)
            self.assertEqual(state['process_state'], 'abandoned')
            self.assertEqual(state['blocked_reason'], 'legacy dead')
            self.assertTrue(state['recovery_audits'][0]['path'])
            consumer_claims.release(self.root, self.lease.stem, kind='lease',
                                    actor='operator', reason='legacy dead')
        self.assertEqual((run_dir / 'review_run.before_abandonment.json').read_bytes(), original)
        self.assertEqual((run_dir / 'stdout.log').read_bytes(), b'legacy output')
        self.assertEqual(self.consumer.process_once()['status'], 'resolved')
        self.assertEqual(len(self.launches), 1)

    def test_legacy_run_reuse_and_unknown_creation_fence_operator_release(self):
        self.prepare()
        request, _ = dispatcher.create_review_request(self.root, self.assignment_id)
        state_path = self.root / 'runtime/dispatch/reviews' / request['review_run_id'] / 'review_run.json'
        atomic_write_json(self.lease, dict(review_run_id=request['review_run_id'],
                                          acquired_at='2099-01-01T00:00:00Z'))
        atomic_write_json(state_path, dict(pid=35728, process_start_time=None,
            process_state='running', started_at='2026-08-14T15:56:10Z'))
        recorded = datetime(2026, 8, 14, 15, 56, 10, tzinfo=timezone.utc)
        ticks = int(recorded.timestamp() * 10000000) + 116444736000000000
        for actual in (str(ticks - 10000000), str(ticks), 'unreadable'):
            with patch('orchestrator.consumer_claims.os.name', 'nt'), patch(
                    'orchestrator.consumer_claims.process_start_time', return_value=actual):
                with self.assertRaisesRegex(ValueError, 'live or unknown'):
                    consumer_claims.release(self.root, self.lease.stem, kind='lease',
                                            actor='operator', reason='reuse')
        with patch('orchestrator.consumer_claims.os.name', 'nt'), patch(
                'orchestrator.consumer_claims.process_start_time', return_value=str(ticks + 10000000)):
            consumer_claims.release(self.root, self.lease.stem, kind='lease',
                                    actor='operator', reason='reuse')
        self.assertEqual(consumer_claims.read_record(state_path)['process_state'], 'abandoned')

    def test_legacy_capacity_is_visible_readable_and_operator_release_retries_once(self):
        self.prepare()
        atomic_write_json(self.lease, dict(holder='claude-reviewer', acquired_at='2026-08-14T15:56:09Z'))
        self.consumer.process_once()
        self.assertEqual(self.launches, [])
        status = load_watcher_status(self.root)
        self.assertEqual(status['lifecycle_state'], 'blocked_stale_lease')
        self.assertTrue(status['stale_review_lease_alert_active'])
        self.assertTrue(status['alert_active'])
        self.assertEqual(status['stale_review_leases'][0]['key'], self.lease.stem)
        self.assertEqual(consumer_claims.list_records(self.root)['leases'][0]['key'], self.lease.stem)
        from contextlib import redirect_stdout
        from io import StringIO
        from scripts.consumer_claims import main
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['--root', str(self.root), 'list']), 0)
        self.assertEqual(json.loads(output.getvalue())['leases'][0]['key'], self.lease.stem)
        path = consumer_claims.directory(self.root) / 'deferred' / f'{self.fp}.json'
        deferred = consumer_claims.read_record(path)
        self.assertEqual(deferred['blocked_on'], 'capacity:review')
        self.assertIn('review concurrency', deferred['reason'])
        self.assertEqual(deferred['attempt_count'], 0)
        self.assertEqual([e for e in self.events if e['event'] == 'deferred'][0]['reason'], deferred['reason'])
        self.assertLessEqual((datetime.fromisoformat(deferred['next_eligible_at'].replace('Z', '+00:00')) - self.clock).total_seconds(), 30)
        # Repeated capacity checks never turn into failed attempts.
        for _ in range(3):
            self.clock += timedelta(seconds=31)
            self.consumer.process_once()
            self.assertEqual(consumer_claims.read_record(path)['attempt_count'], 0)
        consumer_claims.release(self.root, self.lease.stem, kind='lease', actor='operator', reason='confirmed abandoned')
        self.assertEqual(self.consumer.process_once()['status'], 'resolved')
        self.consumer.process_once()
        self.assertEqual(len(self.launches), 1)
        self.assertFalse(load_watcher_status(self.root)['stale_review_leases'])

    def test_dead_consumer_no_child_and_dead_child_recover_claim_and_lease_once(self):
        self.prepare()
        self.abandoned(review_pid=222, review_start_time='dead-child')
        claim = consumer_claims.directory(self.root) / 'claims' / f'{self.fp}.json'
        atomic_write_json(claim, dict(consumer_claims.read_record(self.lease), fingerprint=self.fp))
        with patch('orchestrator.consumer_claims.process_liveness', return_value=False):
            self.assertEqual(self.consumer.process_once()['status'], 'resolved')
            self.consumer.process_once()
        self.assertEqual(len(self.launches), 1)
        audits = [consumer_claims.read_record(p) for p in (consumer_claims.directory(self.root) / 'audit').glob('*.json')]
        self.assertEqual(sorted(a['event'] for a in audits), ['claim_recovered', 'lease_recovered'])
        self.assertTrue(all(a['prior_owner']['consumer_token'] == 'dead' and a['reason'] for a in audits))
        self.assertFalse(claim.exists())
        self.assertFalse(self.lease.exists())

    def test_no_recorded_child_recovers_before_capacity_check(self):
        self.prepare()
        prior = self.abandoned()
        # A reused PID proves that the recorded consumer has died.
        with patch('orchestrator.consumer_claims.process_start_time', return_value='new-owner'):
            self.assertEqual(self.consumer.process_once()['status'], 'resolved')
        self.assertEqual(len(self.launches), 1)
        audits = [consumer_claims.read_record(p) for p in (consumer_claims.directory(self.root) / 'audit').glob('*.json')]
        self.assertEqual(audits[0]['event'], 'lease_recovered')
        self.assertIn('no review child recorded', audits[0]['reason'])
        request = consumer_claims.read_record(dispatcher.review_request_path(self.root, self.assignment_id))
        self.assertEqual(request['review_run_id'], prior['review_run_id'])
        self.assertEqual(request['status'], 'applied')

    def test_crashed_attempt_evidence_and_lineage_survive_retry(self):
        self.prepare()
        prior = self.abandoned(review_pid=222, review_start_time='dead-child')
        run_dir = self.root / 'runtime/dispatch/reviews' / prior['review_run_id']
        original = (json.dumps(dict(review_run_id=prior['review_run_id'],
            assignment_id=self.assignment_id, task_id='test', process_state='running',
            pid=222, process_start_time='dead-child', started_at='2026-10-22T11:14:57Z')) + '\n').encode()
        (run_dir / 'review_run.json').write_bytes(original)
        (run_dir / 'stdout.log').write_bytes(b'partial review\r\n\x00')
        (run_dir / 'stderr.log').write_bytes(b'old stderr')
        (run_dir / 'prompt.txt').write_bytes(b'old prompt')
        claim = consumer_claims.directory(self.root) / 'claims' / f'{self.fp}.json'
        atomic_write_json(claim, dict(prior, fingerprint=self.fp))
        with patch('orchestrator.consumer_claims.process_liveness', return_value=False), patch.object(
                dispatcher, 'apply_verdict', wraps=dispatcher.apply_verdict) as apply:
            self.assertEqual(self.consumer.process_once()['status'], 'resolved')
            self.consumer.process_once()
            replay = dispatcher.process_one_review(self.root, assignment_id=self.assignment_id)
            self.assertTrue(replay['recovered'])
            self.assertEqual(apply.call_count, 1)
        request = consumer_claims.read_record(dispatcher.review_request_path(self.root, self.assignment_id))
        self.assertNotEqual(request['review_run_id'], prior['review_run_id'])
        self.assertEqual(request['prior_review_run_ids'], [prior['review_run_id']])
        attempt = consumer_claims.read_record(self.root / 'runtime/dispatch/reviews' /
                                              request['review_run_id'] / 'attempt.json')
        self.assertEqual(sorted(a['event'] for a in attempt['recovery_audits']),
                         ['claim_recovered', 'lease_recovered'])
        self.assertTrue(all((self.root / a['path']).is_file() for a in attempt['recovery_audits']))
        self.assertEqual((run_dir / 'review_run.before_abandonment.json').read_bytes(), original)
        state = consumer_claims.read_record(run_dir / 'review_run.json')
        self.assertEqual(state['process_state'], 'abandoned')
        self.assertEqual(state['pid'], 222)
        self.assertEqual(state['process_start_time'], 'dead-child')
        self.assertEqual(state['started_at'], '2026-10-22T11:14:57Z')
        self.assertTrue(state['blocked_reason'])
        self.assertEqual((run_dir / 'stdout.log').read_bytes(), b'partial review\r\n\x00')
        self.assertEqual((run_dir / 'stderr.log').read_bytes(), b'old stderr')
        self.assertEqual((run_dir / 'prompt.txt').read_bytes(), b'old prompt')
        self.assertEqual(len(self.launches), 1)

    def test_normal_review_uses_original_run_and_files(self):
        self.prepare()
        request, errors = dispatcher.create_review_request(self.root, self.assignment_id)
        self.assertEqual(errors, [])
        self.assertEqual(self.consumer.process_once()['status'], 'resolved')
        current = consumer_claims.read_record(dispatcher.review_request_path(self.root, self.assignment_id))
        self.assertEqual(current['review_run_id'], request['review_run_id'])
        run_dir = self.root / 'runtime/dispatch/reviews' / current['review_run_id']
        self.assertEqual(consumer_claims.read_record(run_dir / 'attempt.json')['prior_review_run_ids'], [])
        for name in ('context_bundle.json', 'prompt.txt', 'stdout.log', 'stderr.log', 'review_run.json'):
            self.assertTrue((run_dir / name).is_file(), name)
        self.assertEqual(len(list(run_dir.parent.iterdir())), 1)

    def test_retry_reservation_updates_lease_liveness_and_retains_full_history(self):
        self.prepare()
        request, _ = dispatcher.create_review_request(self.root, self.assignment_id)
        first = request['review_run_id']
        self.assertTrue(dispatcher.try_acquire_review_lease(self.root,
            assignment_id=self.assignment_id, review_run_id=first)[0])
        self.assertEqual(dispatcher.prepare_review_attempt(self.root, request), first)
        second = dispatcher.prepare_review_attempt(self.root, request)
        self.assertNotEqual(first, second)
        third = dispatcher.prepare_review_attempt(self.root, request)
        self.assertEqual(request['prior_review_run_ids'], [first, second])
        lease = consumer_claims.read_record(self.lease)
        self.assertEqual(lease['review_run_id'], third)
        atomic_write_json(self.root / 'runtime/dispatch/reviews' / third / 'review_run.json',
                          dict(pid=333, process_start_time='latest-child'))
        self.assertEqual(consumer_claims._review_evidence(self.root, lease), [(333, 'latest-child', None)])

    def test_live_unknown_owner_or_child_preserves_lease(self):
        self.prepare()
        for owner, child in [(True, False), (None, False), (False, True), (False, None)]:
            with self.subTest(owner=owner, child=child):
                self.abandoned(review_pid=222, review_start_time='child')
                before = self.lease.read_bytes()
                with patch('orchestrator.consumer_claims.process_liveness',
                           side_effect=lambda pid, start: owner if pid == 111 else child):
                    ok, _ = dispatcher.try_acquire_review_lease(self.root, assignment_id='other', review_run_id='other')
                self.assertFalse(ok)
                self.assertEqual(self.lease.read_bytes(), before)
        self.assertEqual(self.launches, [])

    def test_run_state_child_fences_even_if_not_recorded_in_lease(self):
        self.prepare()
        prior = self.abandoned()
        atomic_write_json(self.root / 'runtime/dispatch/reviews' / prior['review_run_id'] / 'review_run.json',
                          dict(pid=222, process_start_time='child'))
        for child in (True, None):
            with patch('orchestrator.consumer_claims.process_liveness',
                       side_effect=lambda pid, start: False if pid == 111 else child):
                ok, _ = dispatcher.try_acquire_review_lease(self.root, assignment_id='other', review_run_id='other')
            self.assertFalse(ok)
            self.assertTrue(self.lease.exists())

    def test_incomplete_identity_and_unreadable_evidence_stay_fenced(self):
        self.prepare()
        for extra in [dict(consumer_start_time=None), dict(consumer_token=None),
                      dict(review_pid=222, review_start_time=None)]:
            with self.subTest(extra=extra):
                self.abandoned()
                prior = consumer_claims.read_record(self.lease)
                prior.update(extra)
                atomic_write_json(self.lease, prior)
                with patch('orchestrator.consumer_claims.process_start_time', return_value='reused'):
                    self.assertEqual(consumer_claims.recover_review_leases(self.root), [])
                self.assertTrue(self.lease.exists())
        prior = self.abandoned()
        run = self.root / 'runtime/dispatch/reviews' / prior['review_run_id'] / 'review_run.json'
        run.write_text('{bad json')
        with patch('orchestrator.consumer_claims.process_liveness', return_value=False):
            self.assertEqual(consumer_claims.recover_review_leases(self.root), [])
        self.assertTrue(self.lease.exists())

    def test_audit_failure_keeps_lease(self):
        self.prepare()
        self.abandoned()
        with patch('orchestrator.consumer_claims.process_liveness', return_value=False), patch(
                'orchestrator.consumer_claims.audit', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                consumer_claims.recover_review_leases(self.root)
        self.assertTrue(self.lease.exists())

    def test_competing_recovery_acquires_only_one_slot(self):
        from concurrent.futures import ThreadPoolExecutor
        self.prepare()
        self.abandoned(review_pid=222, review_start_time='dead-child')
        def alive(pid, start):
            return False if pid in (111, 222) else True
        def acquire(index):
            return dispatcher.try_acquire_review_lease(self.root,
                assignment_id=f'contender-{index}', review_run_id=f'run-{index}')[0]
        with patch('orchestrator.consumer_claims.process_liveness', side_effect=alive), ThreadPoolExecutor(2) as pool:
            results = list(pool.map(acquire, range(2)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(dispatcher.count_active_review_leases(self.root), 1)
        audits = list((consumer_claims.directory(self.root) / 'audit').glob('*.json'))
        self.assertEqual(len(audits), 1)

    def test_live_lease_is_capacity_without_stale_alert(self):
        self.prepare()
        self.abandoned(review_pid=222, review_start_time='child')
        with patch('orchestrator.consumer_claims.process_liveness', return_value=True):
            result = self.consumer.process_once()
            self.consumer.process_once()
        self.assertEqual(result['blocked_on'], 'capacity:review')
        status = load_watcher_status(self.root)
        self.assertEqual(status['lifecycle_state'], 'blocked_capacity')
        self.assertFalse(status['stale_review_leases'])
        self.assertFalse(status['stale_review_lease_alert_active'])

    def test_assignment_lease_remains_capacity_when_other_slots_free(self):
        self.prepare()
        self.abandoned()
        with patch('orchestrator.consumer_claims.process_liveness', return_value=True):
            ok, reason = dispatcher.try_acquire_review_lease(self.root,
                assignment_id=self.assignment_id, review_run_id='other', max_concurrency=2)
        self.assertFalse(ok)
        self.assertTrue(reason.startswith('blocked_capacity:'))

    def test_unreadable_lease_counts_and_alerts(self):
        self.prepare()
        self.lease.write_text('{bad json')
        self.consumer.process_once()
        status = load_watcher_status(self.root)
        self.assertEqual(status['lifecycle_state'], 'blocked_stale_lease')
        self.assertIsNone(status['stale_review_leases'][0]['age_seconds'])
        self.assertEqual(dispatcher.count_active_review_leases(self.root), 1)
        self.assertEqual(self.launches, [])
        self.assertEqual(consumer_claims.list_records(self.root)['leases'][0]['key'], self.lease.stem)
        self.assertTrue(consumer_claims.list_records(self.root)['leases'][0]['error'])

    def test_deferral_reason_preserved_for_auth_and_failure(self):
        self.prepare()
        for status, reason in [('blocked_auth', 'login required'), ('failed_launch', 'executable missing')]:
            self.consumer.processor = lambda **kw: dict(status=status, blocked_reason=reason)
            self.clock += timedelta(days=1)
            self.consumer.process_once()
            state = self.consumer._load_deferred(self.fp)
            self.assertEqual(state['reason'], reason)
            self.assertEqual([e for e in self.events if e['event'] == 'deferred'][-1]['reason'], reason)


if __name__ == '__main__':
    unittest.main()
