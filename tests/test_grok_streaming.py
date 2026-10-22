"""Offline regressions using the captured stream and a format-sensitive fake CLI."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from orchestrator.failure_classify import classify_process_output
from orchestrator.grok_stream import record_terminal
from orchestrator.run_deadlines import DeadlinePolicy, StreamActivity
from orchestrator.runtime_store import load_run_state
from orchestrator.supervisor import SupervisorConfig, process_wake_signal
from tests.test_physical_agent_launcher import PhysicalLauncherFixture
from tests import test_run_deadlines as deadlines


FIXTURE = Path(__file__).parent / 'fixtures/real_provider_errors/grok_streaming/success_streaming_json.ndjson'


class StreamingTests(unittest.TestCase):
    setUp = deadlines.DeadlineMonitorTests.setUp
    run_process = deadlines.DeadlineMonitorTests.run_process
    def test_real_events_and_terminal_metadata(self):
        stdout = FIXTURE.read_text(encoding='utf-8')
        self.stdout.write_text(stdout, encoding='utf-8')
        activity = StreamActivity(self.stdout, grok_stream=True)
        self.assertEqual(activity.poll(), 9)
        self.assertEqual(activity.poll(), 0)
        record_terminal(self.state, stdout)
        self.assertEqual(self.state.session_id, '01a164ca-efd2-7bd3-9f67-3ad42abb18f6')
        self.assertEqual(self.state.stop_reason, 'end_turn')
        self.assertEqual(self.state.token_usage, {'input_tokens': 45626, 'output_tokens': 106, 'total_tokens': 48036})

    def test_malformed_lines_are_liveness_only(self):
        self.state.adapter = 'composer-restricted'
        self.stdout.write_text('not JSON\n')
        result, process = self.run_process()
        self.assertEqual(result.deadline_state, 'failed_launch')
        self.assertTrue(process.killed)
        self.assertEqual(self.state.activity_events, 0)
        self.assertEqual(self.state.liveness_events, 1)

    def test_terminal_classification(self):
        def classify(stdout, code=0):
            return classify_process_output(agent='composer', adapter='composer-restricted',
                                           stdout=stdout, exit_code=code)
        stdout = FIXTURE.read_text(encoding='utf-8')
        self.assertEqual(classify(stdout).process_state, 'completed')
        for output, code in [(stdout, 2), (stdout, None), ('', 0), ('{"type":"text","data":"OK"}', 0)]:
            result = classify(output, code)
            self.assertEqual(result.process_state, 'failed')
            self.assertFalse(result.retry_eligible)
        # Synthetic envelope shapes, using only captured provider diagnostic text.
        diagnostic = (FIXTURE.parent.parent / 'grok_402.txt').read_text(encoding='utf-8')
        for event in [{'type': 'error', 'error': diagnostic},
                      {'type': 'error', 'data': diagnostic},
                      {'type': 'end', 'stopReason': 'error', 'error': diagnostic}]:
            self.assertEqual(classify(json.dumps(event)).process_state, 'blocked_quota')
        self.assertEqual(classify('{"type":"end","stopReason":"error"}').process_state, 'failed')


class FormatSensitiveFlowTests(PhysicalLauncherFixture):
    def test_adapter_streams_past_startup_and_inactivity(self):
        clock = deadlines.Clock()
        (self.root/'agents/run_deadlines.yaml').write_text(
            'composer-restricted:\n  startup_seconds: 3\n  inactivity_seconds: 4\n')
        processes = []
        def popen(argv, **kwargs):
            mode = argv[argv.index('--output-format') + 1]
            self.assertEqual(mode, 'streaming-json')
            class FakeGrok(deadlines.Process):
                def poll(inner):
                    # json mode remains silent until exit, beyond startup.
                    if mode == 'streaming-json' and inner.events and clock() >= inner.events[0]:
                        inner.events.pop(0)
                        with inner.path.open('a', encoding='utf-8') as stream:
                            stream.write('{"type":"thought","data":"working"}\n')
                    if clock() >= 12:
                        with inner.path.open('a', encoding='utf-8') as stream:
                            stream.write(FIXTURE.read_text(encoding='utf-8'))
                        return 0
                    return None
            process = FakeGrok(clock, Path(kwargs['stdout'].name), events=[0, 2, 4, 6, 8, 10])
            processes.append(process)
            return process
        with patch('orchestrator.process_monitor.time.monotonic', clock), \
             patch('orchestrator.process_monitor.time.sleep', clock.sleep):
            report = process_wake_signal(self.root, self.wake_path,
                config=SupervisorConfig(allow_codex_fallback=False, timeout_seconds=20),
                popen=popen, launch_plan_builder=self._plan_ok)
        self.assertEqual(report['process_state'], 'completed')
        self.assertFalse(processes[0].killed)
        state = load_run_state(self.root, report['run_id'])
        self.assertGreater(state.activity_events, 6)
        self.assertIsNone(state.deadline_fired)
        self.assertEqual(state.token_usage['total_tokens'], 48036)
        self.assertIsNotNone(state.session_id)
