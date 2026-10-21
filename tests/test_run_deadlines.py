"""Three deadlines with deterministic clocks and fake agent processes only."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dispatch import work_lock
from dispatch.orchestrator_pokes import list_orchestrator_pokes
from orchestrator.process_monitor import monitor_process
from orchestrator.run_deadlines import DeadlinePolicy, StreamActivity, genuine_event
from orchestrator.runtime_store import RunState, load_run_state
from orchestrator.supervisor import SupervisorConfig, process_wake_signal
from orchestrator.claude_reviewer_adapter import ClaudeReviewerAdapter, load_review_state
from orchestrator.review_dispatcher import process_one_review
from tests import test_physical_agent_launcher as physical
from tests import test_claude_reviewer_adapter as review


class Clock:
    now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Process:
    pid = 1234
    killed = False

    def __init__(self, clock, path, events=(), finish=None, write=None):
        self.clock, self.path = clock, path
        self.events = list(events)
        self.finish, self.write = finish, write

    def poll(self):
        while self.events and self.clock() >= self.events[0]:
            self.events.pop(0)
            with self.path.open('a', encoding='utf-8') as stream:
                stream.write('{"type":"turn.started"}\n')
            if self.write:
                self.write()
        return 0 if self.killed or (self.finish is not None and self.clock() >= self.finish) else None

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return -9 if self.killed else 0


class DeadlineMonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.clock = Clock()
        self.stdout = self.root / 'stdout.log'
        self.state = RunState('run', 'assignment', 'task', 'codex', 'codex-restricted',
                              process_state='running', pid=1234)

    def run_process(self, events=(), finish=None, policy=DeadlinePolicy(3, 4, 20), **kwargs):
        process = Process(self.clock, self.stdout, events, finish)
        result = monitor_process(
            process, state=self.state, repo_root=self.root, stdout_path=self.stdout,
            stderr_path=self.root/'stderr.log', timeout_seconds=20,
            heartbeat_seconds=1, clock_fn=self.clock, sleep_fn=self.clock.sleep,
            deadline_policy=policy, **kwargs)
        return result, process

    def test_startup_requires_genuine_activity(self):
        self.stdout.write_text('{"type":"system","subtype":"init"}\nheartbeat\n')
        result, process = self.run_process()
        self.assertEqual(result.deadline_state, 'failed_launch')
        self.assertTrue(process.killed)
        self.assertEqual(self.state.activity_events, 0)
        self.assertEqual(load_run_state(self.root, 'run').deadline_fired, 'startup')

    def test_activity_then_silence_stalls_despite_liveness_and_heartbeats(self):
        result, process = self.run_process(events=(0,))
        self.assertEqual(result.deadline_state, 'stalled')
        self.assertEqual(self.clock(), 4)
        durable = load_run_state(self.root, 'run')
        self.assertEqual(durable.activity_events, 1)
        self.assertEqual(durable.deadline_fired, 'inactivity')
        self.assertIsNotNone(durable.deadline_fired_at)
        self.assertIsNotNone(durable.startup_activity_at)
        self.assertIsNotNone(durable.last_activity_at)

    def test_long_active_run_completes_past_both_windows(self):
        result, process = self.run_process(events=range(0, 15, 2), finish=15)
        self.assertIsNone(result.deadline_state)
        self.assertFalse(process.killed)
        self.assertEqual(self.state.activity_events, 8)
        self.assertGreater(self.clock(), 4)

    def test_continuing_activity_does_not_extend_overall(self):
        result, process = self.run_process(events=range(30))
        self.assertEqual(result.deadline_state, 'timed_out')
        self.assertEqual(self.clock(), 20)
        self.assertTrue(process.killed)

    def test_worktree_write_counts_but_runtime_and_logs_do_not(self):
        worktree = self.root/'worktree'
        worktree.mkdir()
        (worktree/'runtime').mkdir()
        def sleep(seconds):
            self.clock.sleep(seconds)
            (worktree/'runtime'/'heartbeat').write_text(str(self.clock()))
            if self.clock() == 2:
                (worktree/'code.py').write_text('print(1)')
        process = Process(self.clock, self.stdout)
        result = monitor_process(process, state=self.state, repo_root=self.root,
            stdout_path=self.stdout, stderr_path=self.root/'stderr.log', timeout_seconds=20,
            deadline_policy=DeadlinePolicy(3,4,20), heartbeat_seconds=1,
            clock_fn=self.clock, sleep_fn=sleep, worktree=worktree)
        self.assertEqual(result.deadline_state, 'stalled')
        self.assertEqual(self.clock(), 6)
        self.assertEqual(self.state.activity_events, 1)

    def test_partial_stream_and_repeated_reads_count_once(self):
        source = StreamActivity(self.stdout)
        self.stdout.write_text('{"type":"turn.')
        self.assertEqual(source.poll(), 0)
        with self.stdout.open('a') as stream:
            stream.write('started"}\n')
        self.assertEqual(source.poll(), 1)
        self.assertEqual(source.poll(), 0)

    def test_structured_activity_sources(self):
        for event in [
            {'type':'stream_event','event':{'type':'content_block_delta'}},
            {'type':'item.started','item':{'type':'command_execution'}},
            {'type':'assistant','message':{'content':'working'}},
        ]:
            self.assertTrue(genuine_event(event))
        for event in [{'type':'thread.started'}, {'type':'heartbeat'}, {'type':'system'},
                      {'event': {}}, {'type': []},
                      {'type': 'item.started', 'item': {'type': []}}, 'noise']:
            self.assertFalse(genuine_event(event))


class BuilderDeadlineFlowTests(physical.PhysicalLauncherFixture):
    def run_deadline(self, expected, events, overall=20):
        clock = Clock()
        (self.root/'agents'/'run_deadlines.yaml').write_text(
            'composer-restricted:\n  startup_seconds: 3\n  inactivity_seconds: 4\n')
        processes = []
        def popen(argv, **kwargs):
            process = Process(clock, Path(kwargs['stdout'].name), events)
            processes.append(process)
            return process
        with patch('orchestrator.process_monitor.time.monotonic', clock), patch('orchestrator.process_monitor.time.sleep', clock.sleep):
            report = process_wake_signal(self.root, self.wake_path,
                config=SupervisorConfig(allow_codex_fallback=True, timeout_seconds=overall),
                popen=popen, launch_plan_builder=self._plan_ok)
        self.assertEqual(report['process_state'], expected)
        self.assertEqual(len(processes), 1)
        self.assertTrue(processes[0].killed)
        state = load_run_state(self.root, report['run_id'])
        self.assertEqual(state.process_state, expected)
        self.assertTrue(Path(state.worktree).is_dir())
        self.assertEqual(len(work_lock.status(self.root)), 1)
        pokes, errors = list_orchestrator_pokes(self.root)
        self.assertEqual(errors, [])
        self.assertEqual([poke['event'] for poke in pokes], ['assignment_failed'])

    def test_startup_terminal_poke_and_retained_lock(self):
        self.run_deadline('failed_launch', ())

    def test_inactivity_terminal_poke_and_retained_lock(self):
        self.run_deadline('stalled', (0,))

    def test_overall_terminal_poke_and_retained_lock(self):
        self.run_deadline('timed_out', range(30), overall=10)


class ReviewerDeadlineFlowTests(unittest.TestCase):
    setUp = review.ReviewFlowFixture.setUp
    tearDown = review.ReviewFlowFixture.tearDown

    def test_launch_error_emits_one_poke_and_retains_lock(self):
        def popen(argv, **kwargs):
            raise OSError('fake launch failure')
        adapter = ClaudeReviewerAdapter(self.root, claude_executable='python', popen=popen)
        report = process_one_review(self.root, assignment_id=self.assignment_id, adapter=adapter)
        self.assertEqual(report['status'], 'failed_launch')
        self.assertEqual(len(work_lock.status(self.root)), 1)
        pokes, _ = list_orchestrator_pokes(self.root)
        self.assertEqual(sum(poke['event'] == 'review_failed_launch' for poke in pokes), 1)

    def run_deadline(self, expected, events, overall=20):
        clock = Clock()
        def popen(argv, **kwargs):
            return Process(clock, Path(kwargs['stdout'].name), events)
        adapter = ClaudeReviewerAdapter(self.root, claude_executable='python', popen=popen)
        with patch('orchestrator.process_monitor.time.monotonic', clock), patch('orchestrator.process_monitor.time.sleep', clock.sleep):
            report = process_one_review(self.root, assignment_id=self.assignment_id,
                adapter=adapter, timeout_seconds=overall, activity_timeout_seconds=3,
                inactivity_timeout_seconds=4)
        self.assertEqual(report['status'], expected)
        state = load_review_state(self.root, report['review_run_id'])
        self.assertEqual(state.process_state, expected)
        self.assertIsNotNone(state.deadline_fired_at)
        self.assertEqual(len(work_lock.status(self.root)), 1)
        pokes, _ = list_orchestrator_pokes(self.root)
        self.assertEqual(sum(poke['event'] == f'review_{expected}' for poke in pokes), 1)
        self.assertEqual(report['assignment_status'], 'awaiting_review')

    def test_startup(self):
        self.run_deadline('failed_launch', ())

    def test_inactivity(self):
        self.run_deadline('stalled', (0,))

    def test_overall(self):
        self.run_deadline('timed_out', range(30), overall=10)

class LocalBuilderDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.worktree = self.root/'worktree'
        self.worktree.mkdir()
        (self.root/'agents').mkdir()
        (self.root/'agents'/'run_deadlines.yaml').write_text(
            'codex-restricted:\n  startup_seconds: 3\n  inactivity_seconds: 4\n')
        self.task_path = self.root/'task.yaml'
        self.task_path.write_text('id: T-LOCAL\nexecution:\n  timeout_seconds: 10\n')

    def run_deadline(self, expected, events):
        from contextlib import ExitStack
        from types import SimpleNamespace
        from dispatch.local_builder_core import run_adapter_local_builder, LocalBuilderRunConfig, CommandPlan
        from orchestrator.agent_launcher import launch_process
        clock = Clock()
        def launch(plan, **kwargs):
            def popen(argv, **options):
                self.assertEqual(options['env'], {})
                return Process(clock, Path(options['stdout'].name), events)
            return launch_process(plan, **kwargs, popen=popen)
        allocation = SimpleNamespace(success=True, record={}, worktree_path=str(self.worktree), branch_name='branch')
        with ExitStack() as stack:
            for name, value in {
                'load_execution_policy': {}, 'allocate_worktree': allocation,
                'allocation_record_to_dict': {'worktree_path':str(self.worktree)},
                'build_context_bundle': {}, '_git_porcelain_status':'', '_git_changed_files':[],
                '_git_diff_patch':'', 'git_worktree_head':'base', 'git_worktree_dirty':False,
            }.items():
                stack.enter_context(patch('dispatch.local_builder_core.'+name, return_value=value))
            stack.enter_context(patch('dispatch.local_builder_core.launch_process', side_effect=launch))
            stack.enter_context(patch('orchestrator.process_monitor.time.monotonic', clock))
            stack.enter_context(patch('orchestrator.process_monitor.time.sleep', clock.sleep))
            result = run_adapter_local_builder(self.root, task_path=self.task_path, adapter={},
                config=LocalBuilderRunConfig('codex-restricted','codex_local_builder','codex','codex','runtime/output.json'),
                evaluate_gates=lambda *a, **k: SimpleNamespace(allowed=True),
                build_command_plan=lambda **kwargs: CommandPlan(['fake-codex','--json'],str(self.worktree)),
                prepare_environment=lambda adapter: ({},[],None), resolve_executable=lambda name:name,
                base_sha='base')
        self.assertEqual(result.status, expected)
        self.assertEqual(result.verification_results['commands'], [])
        self.assertEqual(work_lock.status(self.root)[0]['state'], expected)
        record = json.loads((Path(result.run_dir)/'result.json').read_text())
        self.assertIsNotNone(record['deadline_fired_at'])
        self.assertEqual(len(list_orchestrator_pokes(self.root)[0]), 1)
        self.assertTrue(self.worktree.is_dir())

    def test_startup(self):
        self.run_deadline('failed_launch', ())

    def test_inactivity(self):
        self.run_deadline('stalled', (0,))

    def test_overall(self):
        self.run_deadline('timed_out', range(20))

class WorkerDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def check_deadline(self, status):
        import importlib.util
        from types import SimpleNamespace
        from dispatch.assignment_channel import write_assignment, read_assignment
        spec = importlib.util.spec_from_file_location('deadline_worker', Path(__file__).resolve().parents[1]/'scripts/run_local_builder_worker.py')
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        assignment, errors = write_assignment(self.root, task_id='T-WORKER', assigned_to='codex')
        self.assertEqual(errors, [])
        task = self.root/'task.yaml'
        task.write_text('id: T-WORKER\n')
        def result(*args, **kwargs):
            return SimpleNamespace(run_id=kwargs['work_lock_run_id'], task_id='T-WORKER', status=status,
                worktree_path='', handoff_path='', blocked_reasons=[status])
        with patch.object(worker,'load_execution_policy', return_value={'maximum_concurrent_runs':1}), patch.object(worker,'run_local_builder', side_effect=result):
            report = worker.process_one(self.root, task_path=task)
        self.assertEqual(report['result_status'], status)
        self.assertEqual(read_assignment(self.root, assignment.stem)[0].status, 'reviewable_failure')
        self.assertEqual(work_lock.status(self.root)[0]['state'], status)
        self.assertEqual([p['event'] for p in list_orchestrator_pokes(self.root)[0]], ['assignment_failed'])

    def test_startup(self):
        self.check_deadline('failed_launch')

    def test_inactivity(self):
        self.check_deadline('stalled')

    def test_overall(self):
        self.check_deadline('timed_out')

class LauncherInputTests(unittest.TestCase):
    def test_local_builder_environment_does_not_inherit_host_secrets(self):
        from types import SimpleNamespace
        from orchestrator.agent_launcher import LaunchPlan, launch_process
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def popen(argv, **kwargs):
                self.assertEqual(kwargs['env'], {'SAFE': 'value'})
                return SimpleNamespace(pid=1234)
            with patch.dict('os.environ', {'HOST_SECRET': 'must-not-inherit'}):
                launch_process(LaunchPlan('codex', 'codex-restricted', ['fake'], directory,
                    'fake', env={'SAFE': 'value'}, inherit_environment=False),
                    stdout_path=root/'stdout', stderr_path=root/'stderr', popen=popen)

    def test_stdin_prompt_is_available_without_a_blocking_pipe_write(self):
        from types import SimpleNamespace
        from orchestrator.agent_launcher import LaunchPlan, launch_process
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prompt = 'prompt\n' * 20000
            def popen(argv, **kwargs):
                self.assertEqual(kwargs['stdin'].read(), prompt)
                return SimpleNamespace(pid=1234)
            handle, _ = launch_process(LaunchPlan('claude','claude-reviewer',['fake'],directory,'fake',stdin_text=prompt),
                stdout_path=root/'stdout',stderr_path=root/'stderr',popen=popen)
            self.assertEqual(handle.pid, 1234)
