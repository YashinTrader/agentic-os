import json
from pathlib import Path
import tempfile
import unittest

from orchestrator.builder_watch import BuilderWatch, state_snapshot, changed_state

ROOT = Path(__file__).resolve().parents[1]


class BuilderWatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.notices = []
        self.contract = {'turn_budget': 30, 'allowed_edit_paths': ['src/**'],
                         'relevant_files': ['.agentic/task.yaml']}
        self.watch = BuilderWatch(self.root, self.contract,
                                 notify=lambda event, detail: self.notices.append((event, detail)))

    def test_replay_real_stream_one_checkpoint_and_outside_diagnostic(self):
        evidence = ROOT/'tests/fixtures/r12_e2e/grok_stdout.jsonl'
        events = [json.loads(line) for line in evidence.read_text(encoding='utf-8').splitlines()]
        self.assertTrue(any(event['type'] == 'max_turns_reached' for event in events))
        self.assertEqual(events[-1]['type'], 'end')
        from orchestrator.failure_classify import classify_process_output
        result = classify_process_output(agent='composer', adapter='composer-restricted',
            exit_code=1, stdout=evidence.read_text(encoding='utf-8'))
        self.assertEqual(result.process_state, 'max_turns')
        self.assertFalse(result.retry_eligible)
        for line in evidence.read_text(encoding='utf-8').splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            self.watch.event(event)
        early = [detail for event, detail in self.notices if event == 'no_early_progress']
        self.assertEqual(len(early), 1)
        self.assertEqual(early[0]['turns_used'], 12)
        self.assertEqual(sum(event == 'isolation_violation' for event, _ in self.notices), 1)
        diagnostic = self.watch.diagnostic()
        self.assertEqual(diagnostic['tool_calls'], 87)
        self.assertEqual(diagnostic['tool_histogram']['read_file'], 38)
        self.assertTrue(diagnostic['out_of_worktree_accesses'])
        self.assertEqual(len(diagnostic['last_10_targets']), 10)

    def test_allowed_diff_or_plan_suppresses_notice(self):
        for mode in ('diff', 'plan'):
            with self.subTest(mode=mode):
                notices = []
                watch = BuilderWatch(self.root, self.contract, notify=lambda *args: notices.append(args))
                path = self.root / ('src/fix.py' if mode == 'diff' else '.agentic/PLAN.md')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('progress')
                for _ in range(12):
                    watch.event({'type': 'usage'})
                self.assertEqual(notices, [])

    def test_snapshot_detects_inbox_claim_and_task_move_excludes_exact_own_files(self):
        for name in ('runtime/dispatch/assignments/inbox/other.json',
                     'runtime/dispatch/assignments/inbox/own.json',
                     'runtime/dispatch/locks/own.json', 'tasks/blocked/other.yaml'):
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('before')
        before = state_snapshot(self.root)
        (self.root/'runtime/dispatch/assignments/inbox/other.json').write_text('claimed')
        (self.root/'runtime/dispatch/assignments/inbox/own.json').write_text('heartbeat')
        (self.root/'runtime/dispatch/locks/own.json').write_text('heartbeat')
        claim = self.root/'runtime/dispatch/assignments/claims/other.json'
        claim.parent.mkdir(parents=True)
        claim.write_text('{}')
        active = self.root/'tasks/active/other.yaml'
        active.parent.mkdir(parents=True)
        (self.root/'tasks/blocked/other.yaml').rename(active)
        changed = changed_state(before, state_snapshot(self.root),
                                ['runtime/dispatch/assignments/inbox/own.json',
                                 'runtime/dispatch/locks/own.json'])
        self.assertEqual(len(changed), 4)
        self.assertIn('runtime/dispatch/assignments/claims/other.json', changed)
        self.assertIn('tasks/blocked/other.yaml', changed)

    def test_outside_references_are_lexical_and_inside_paths_allowed(self):
        self.assertFalse(self.watch._outside(str(self.root/'src/fix.py')))
        self.assertTrue(self.watch._outside('python C:/fake-live/scripts/writer.py'))
        self.assertTrue(self.watch._outside('python ../outside.py'))


if __name__ == '__main__':
    unittest.main()
