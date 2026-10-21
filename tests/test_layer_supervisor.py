from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from dispatch.atomic_io import atomic_write_json
from orchestrator import layer_heartbeat
from orchestrator.layer_supervisor import LayerSupervisor, STDERR_LIMIT, backoff_seconds


class FakeProcess:
    def __init__(self, pid):
        self.pid = pid
        self.returncode = None
        self.stderr = None
        self.signals = []
        self.killed = False

    def poll(self):
        return self.returncode

    def send_signal(self, sig):
        self.signals.append(sig)
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


class LayerSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = 0.0
        self.processes = []
        def launch(*args, **kwargs):
            process = FakeProcess(100 + len(self.processes))
            self.processes.append(process)
            return process
        self.supervisor = LayerSupervisor(self.root, {"builder": ["dummy"], "claude": ["dummy"]},
                                          popen=launch, clock=lambda: self.now)
        self.addCleanup(self.supervisor.shutdown)

    def heartbeat(self, name, ticks=1, progress=None):
        child = self.supervisor.children[name]
        atomic_write_json(child.heartbeat, {"pid": child.process.pid, "token": child.token, "ticks": ticks,
            "last_tick_at": "now", "last_progress_at": progress})

    def test_only_exited_child_restarts_and_recovery_requires_heartbeat(self):
        self.supervisor.step()
        sibling = self.supervisor.children["claude"].process
        self.supervisor.children["builder"].process.returncode = 7
        self.supervisor.step()
        self.now = 1
        self.supervisor.step()
        self.assertEqual(len(self.processes), 2)
        self.now = 2
        self.supervisor.step()
        self.assertEqual(len(self.processes), 3)
        self.assertIs(self.supervisor.children["claude"].process, sibling)
        child = self.supervisor.children["builder"]
        self.assertIsNone(child.status["recovery_seconds"])
        self.heartbeat("builder")
        self.now = 3
        self.supervisor.step()
        self.assertEqual(child.status["recovery_seconds"], 3)
        self.assertEqual(child.status["restart_count"], 1)
        self.assertIsNotNone(child.status["last_restart_at"])
        self.assertFalse(sibling.signals)

    def test_backoff_progression_and_cap(self):
        self.assertEqual([backoff_seconds(i) for i in range(1, 11)],
                         [2, 4, 8, 16, 32, 64, 128, 256, 300, 300])
        self.assertEqual(backoff_seconds(100000), 300)

    def test_crash_loop_keeps_sibling_running_and_preserves_audit(self):
        self.supervisor.step()
        child = self.supervisor.children["builder"]
        sibling = self.supervisor.children["claude"].process
        for i in range(6):
            self.heartbeat("claude", i + 1)
            child.process.returncode = 4
            self.supervisor.step()
            self.now = child.due
            self.supervisor.step()
        self.assertEqual(child.status["state"], "crash_loop")
        self.assertIn("5 exits", child.status["reason"])
        self.assertIs(self.supervisor.children["claude"].process, sibling)
        self.assertFalse(sibling.signals)
        saved = json.loads(self.supervisor.path.read_text())["children"]["builder"]
        self.assertEqual(len(saved["exits"]), 6)
        self.assertEqual(saved["exit_code"], 4)
        reloaded = LayerSupervisor(self.root, {"builder": ["dummy"]})
        self.assertEqual(reloaded.children["builder"].status["state"], "crash_loop")

    def test_stale_heartbeat_restarts_as_hung(self):
        self.supervisor.step()
        old = self.supervisor.children["builder"].process
        self.heartbeat("builder")
        self.supervisor.step()
        self.now = 61
        self.heartbeat("claude", 2)
        self.supervisor.step()
        child = self.supervisor.children["builder"]
        self.assertEqual(child.status["reason"], "hung")
        self.assertEqual(child.status["state"], "backoff")
        self.assertTrue(old.killed)
        self.now = 63
        self.supervisor.step()
        self.assertIsNot(child.process, old)

    def test_missing_heartbeat_and_wrong_generation_cannot_mask_hang(self):
        self.supervisor.step()
        child = self.supervisor.children["builder"]
        atomic_write_json(child.heartbeat, {"pid": child.process.pid, "token": "old launch", "ticks": 999})
        self.now = 61
        self.supervisor.step()
        self.assertEqual(child.status["reason"], "hung")

    def test_idle_ticking_is_distinct_from_progress(self):
        self.supervisor.step()
        self.heartbeat("builder")
        self.supervisor.step()
        status = self.supervisor.children["builder"].status
        self.assertTrue(status["alive"])
        self.assertTrue(status["ticking"])
        self.assertFalse(status["progressing"])
        self.heartbeat("builder", 2, "progress")
        self.supervisor.step()
        self.assertTrue(status["progressing"])
        self.now = 61
        self.heartbeat("builder", 3, "progress")
        self.supervisor.step()
        self.assertTrue(status["ticking"])
        self.assertFalse(status["progressing"])

    def test_graceful_shutdown_records_stopped_without_crash(self):
        self.supervisor.step()
        self.supervisor.request_stop()
        self.supervisor.shutdown()
        saved = json.loads(self.supervisor.path.read_text())
        self.assertEqual(saved["state"], "stopped")
        for child in saved["children"].values():
            self.assertEqual(child["state"], "stopped")
            self.assertEqual(child["exits"], [])
            self.assertFalse(child["alive"])

    def test_signal_handlers_stop_run_and_are_restored(self):
        with patch("orchestrator.layer_supervisor.signal.signal", return_value="previous") as register, \
             patch("orchestrator.layer_supervisor.time.sleep", side_effect=lambda _: self.supervisor.request_stop()):
            self.assertEqual(self.supervisor.run(), 0)
        self.assertEqual(self.supervisor.children["builder"].status["state"], "stopped")
        self.assertGreaterEqual(register.call_count, 4)
        self.assertEqual(register.call_args.args[1], "previous")

    def test_shutdown_terminates_owned_tree(self):
        self.supervisor.step()
        child = self.supervisor.children["builder"]
        self.supervisor.shutdown()
        self.assertTrue(child.process.killed)
        self.assertEqual(child.status["state"], "stopped")
        self.assertEqual(child.status["exits"], [])

    def test_atomic_status_failure_preserves_previous_document(self):
        self.supervisor.step()
        before = self.supervisor.path.read_bytes()
        with patch("dispatch.atomic_io.os.replace", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.supervisor.save()
        self.assertEqual(self.supervisor.path.read_bytes(), before)
        self.assertIsInstance(json.loads(before), dict)

    def test_launch_error_is_backed_off_independently(self):
        with patch.object(self.supervisor, "popen", side_effect=[OSError("missing"), FakeProcess(5)]):
            self.supervisor.step()
        status = self.supervisor.children["builder"].status
        self.assertEqual(status["reason"], "launch_failed")
        self.assertIn("missing", status["stderr_tail"])
        self.assertTrue(self.supervisor.children["claude"].status["alive"])

    def test_real_dummy_crash_restarts_with_bounded_stderr_and_recovery(self):
        script = self.root / "dummy.py"
        script.write_text(
            "import os,sys,time,json\n"
            "from pathlib import Path\n"
            "path=Path(os.environ['AGENTIC_LAYER_HEARTBEAT'])\n"
            "marker=path.with_suffix('.marker')\n"
            "if not marker.exists():\n"
            " marker.write_text('1')\n"
            " sys.stderr.write('x'*20000+' crash evidence'); sys.stderr.flush()\n"
            " sys.exit(17)\n"
            "path.write_text(json.dumps({'pid':os.getpid(),'token':os.environ['AGENTIC_LAYER_TOKEN'],'ticks':1,'last_tick_at':'ready','last_progress_at':None}))\n"
            "time.sleep(20)\n")
        supervisor = LayerSupervisor(self.root, {"dummy": [sys.executable, str(script)]})
        self.addCleanup(supervisor.shutdown)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            supervisor.step()
            status = supervisor.children["dummy"].status
            if status["recovery_seconds"] is not None:
                break
            time.sleep(0.05)
        self.assertIsNotNone(status["recovery_seconds"], status["state"])
        self.assertGreaterEqual(status["recovery_seconds"], 2)
        self.assertEqual(status["restart_count"], 1)
        saved = json.loads(supervisor.path.read_text())["children"]["dummy"]
        self.assertEqual(saved["exit_code"], 17)
        self.assertTrue(saved["stderr_tail"].endswith("crash evidence"))
        self.assertLessEqual(len(saved["stderr_tail"]), STDERR_LIMIT)
        self.assertIsNotNone(saved["exited_at"])


class HeartbeatTests(unittest.TestCase):
    def test_idle_and_progress_markers(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "heartbeat.json"
            with patch.dict(os.environ, AGENTIC_LAYER_HEARTBEAT=str(path)), \
                 patch.object(layer_heartbeat, "_last_write", 0), \
                 patch.object(layer_heartbeat, "_last_progress", None):
                layer_heartbeat.tick()
                first = json.loads(path.read_text())
                self.assertIsNone(first["last_progress_at"])
                layer_heartbeat.tick(progress=True)
                second = json.loads(path.read_text())
                self.assertGreater(second["ticks"], first["ticks"])
                self.assertIsNotNone(second["last_progress_at"])

    def test_wait_continues_ticking_until_process_exits(self):
        process = Mock()
        process.wait.side_effect = [subprocess.TimeoutExpired("dummy", 2), 7]
        with patch.object(layer_heartbeat, "tick") as tick:
            self.assertEqual(layer_heartbeat.wait_with_heartbeat(process, 10), 7)
            self.assertEqual(tick.call_count, 2)

    def test_monitor_stop_kills_work_process_before_unwinding(self):
        from orchestrator.process_monitor import monitor_process
        from orchestrator.runtime_store import RunState
        process = FakeProcess(3)
        state = RunState(run_id="run", assignment_id="a", task_id="t",
                         assigned_agent="composer", adapter="composer-restricted",
                         process_state="running", pid=3)
        with patch("orchestrator.process_monitor.tick", side_effect=SystemExit(0)):
            with self.assertRaises(SystemExit):
                monitor_process(process, state=state, repo_root=Path("."),
                                stdout_path=Path("unused"), stderr_path=Path("unused"), timeout_seconds=60)
        self.assertTrue(process.killed)

    def test_blocking_wait_ticks_and_honors_stop(self):
        process = FakeProcess(1)
        with patch.object(layer_heartbeat, "tick") as tick:
            self.assertIsNone(layer_heartbeat.wait_with_heartbeat(process, 10))
            tick.assert_called_once()
        with patch.object(layer_heartbeat, "_stop_requested", True):
            with self.assertRaises(SystemExit):
                layer_heartbeat.tick()


if __name__ == "__main__":
    unittest.main()
