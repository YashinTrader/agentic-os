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
