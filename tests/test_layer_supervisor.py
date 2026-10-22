from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from dispatch.atomic_io import atomic_write_json
from orchestrator import layer_heartbeat
from orchestrator.layer_supervisor import LayerSupervisor, STDERR_LIMIT, GRACE_SECONDS, backoff_seconds


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

    def test_slow_real_child_retained_until_exit(self):
        supervisor = LayerSupervisor(self.root, {"slow": [sys.executable, "-c",
            "import time; time.sleep(6.5)"]}, clock=lambda: self.now)
        supervisor.step()
        child = supervisor.children["slow"]
        old = child.process
        try:
            self.now = 61
            # Simulate an owned termination request that has not yet taken effect.
            with patch("orchestrator.layer_supervisor.terminate_owned") as terminate:
                supervisor.step()
                self.assertEqual(child.status["state"], "terminating")
                self.assertEqual(child.status["terminating_pid"], old.pid)
                self.assertTrue(child.status["terminating_process_start_time"])
                self.assertIs(child.process, old)
                self.assertIsNone(old.poll())
                self.assertFalse(supervisor.stop_requested)
                supervisor.step()
                self.assertGreaterEqual(terminate.call_count, 2)
            self.assertIsNotNone(old.poll())
            self.assertEqual(child.status["state"], "backoff")
            self.now = child.due
            supervisor.step()
            self.assertIsNot(child.process, old)
        finally:
            supervisor.shutdown()

    def test_run_continues_after_child_error(self):
        original = self.supervisor.supervise_child
        ticks = []
        def injected(child, now):
            if child is self.supervisor.children["builder"]:
                raise RuntimeError("one child failed")
            ticks.append(now)
            return original(child, now)
        def stop_after_ticks(_):
            if len(ticks) == 3:
                self.supervisor.request_stop()
        with patch.object(self.supervisor, "supervise_child", side_effect=injected), \
             patch("orchestrator.layer_supervisor.time.sleep", side_effect=stop_after_ticks):
            self.assertEqual(self.supervisor.run(), 0)
        self.assertEqual(len(ticks), 3)
        self.assertEqual(self.supervisor.supervisor_error_count, 3)

    def test_child_exception_isolated_and_breaker_bounds_retries(self):
        self.supervisor.step()
        child = self.supervisor.children["builder"]
        sibling = self.supervisor.children["claude"]
        original = self.supervisor.supervise_child
        def injected(current, now):
            if current is child:
                raise RuntimeError("injected supervision failure")
            return original(current, now)
        with patch.object(self.supervisor, "supervise_child", side_effect=injected):
            for tick in range(1, 7):
                self.heartbeat("claude", tick)
                self.supervisor.step()
                self.assertEqual(sibling.status["ticks"], tick)
        self.assertTrue(child.status["circuit_open"])
        self.assertEqual(child.status["supervisor_error_count"], 6)
        self.supervisor.step()
        self.assertEqual(child.status["state"], "crash_loop")
        saved = json.loads(self.supervisor.path.read_text())
        self.assertEqual(saved["state"], "running")
        self.assertEqual(saved["supervisor_error_count"], 6)
        error = saved["supervisor_errors"][-1]
        self.assertEqual(error["child"], "builder")
        self.assertIn("RuntimeError", error["traceback_tail"])
        self.assertTrue(error["at"])

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

    def test_shutdown_graceful_signal(self):
        self.supervisor.step()
        child = self.supervisor.children["builder"]
        self.supervisor.shutdown()
        self.assertEqual(child.process.signals, [signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM])
        self.assertEqual(child.status["state"], "stopped")
        self.assertEqual(child.status["exits"], [])

    def test_shutdown_escalates_if_child_ignores_signal(self):
        self.supervisor.step()
        process = self.supervisor.children["builder"].process
        events = []
        process.send_signal = lambda sig: events.append(("signal", sig))
        def wait(timeout=None):
            events.append(("wait", timeout))
            if not process.killed:
                raise subprocess.TimeoutExpired("dummy", timeout)
            return process.returncode
        process.wait = wait
        from orchestrator.process_ownership import terminate_owned
        def terminate(proc):
            if proc is process:
                events.append(("terminate_owned", None))
            return terminate_owned(proc)
        with patch("orchestrator.layer_supervisor.terminate_owned", side_effect=terminate):
            self.supervisor.shutdown()
        self.assertEqual(events, [
            ("signal", signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM),
            ("wait", GRACE_SECONDS), ("terminate_owned", None), ("wait", 5)])
        self.assertTrue(process.killed)

    def test_hung_child_forces_termination_without_grace_wait(self):
        self.supervisor.step()
        process = self.supervisor.children["builder"].process
        process.wait = Mock(return_value=-9)
        self.now = 61
        self.heartbeat("claude", 2)
        self.supervisor.step()
        self.assertTrue(process.killed)
        self.assertEqual(process.signals, [])
        process.wait.assert_called_once_with(timeout=5)

    def test_shutdown_terminates_owned_tree(self):
        from orchestrator.process_ownership import terminate_owned, process_start_time, pid_is_alive
        marker = self.root / "grandchild.json"
        code = (
            "import subprocess,sys,time,json,signal; from pathlib import Path; "
            "signal.signal(getattr(signal,'SIGBREAK',signal.SIGTERM),signal.SIG_IGN); "
            "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']); "
            f"Path({str(marker)!r}).write_text(json.dumps(p.pid)); time.sleep(120)"
        )
        supervisor = LayerSupervisor(self.root, {"tree": [sys.executable, "-c", code]})
        supervisor.step()
        process = supervisor.children["tree"].process
        try:
            deadline = time.monotonic() + 15
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(marker.exists())
            grandchild = json.loads(marker.read_text())
            start = process_start_time(grandchild)
            self.assertTrue(start)
            self.assertTrue(pid_is_alive(grandchild, start))
            with patch("orchestrator.layer_supervisor.GRACE_SECONDS", .1):
                supervisor.shutdown()
            deadline = time.monotonic() + 5
            while pid_is_alive(grandchild, start) and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertIsNotNone(process.poll())
            self.assertFalse(pid_is_alive(grandchild, start))
        finally:
            terminate_owned(process)
            process.wait(timeout=5)

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
