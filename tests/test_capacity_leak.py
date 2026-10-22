"""Offline capacity and abandoned prelaunch regressions."""
import json
import os
import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_builder_condition_retry import ConditionRetryFixture, _monitor
from orchestrator.supervisor import process_once
from orchestrator.runtime_store import RunState, save_run_state, load_run_state
from orchestrator.leases import try_acquire_concurrency, has_assignment_lease, release_lease
from orchestrator.supervisor import recover_orphans


class CapacityLeakTests(ConditionRetryFixture):
    def tick(self):
        return process_once(self.root, config=self._config(), popen=self._popen,
                            launch_plan_builder=self._plan, monitor=_monitor('', exit_code=0))

    def queued(self):
        state = RunState(run_id="abandoned", assignment_id=self.assignment_id,
                         task_id=self.task_id, assigned_agent="composer", adapter="composer-restricted",
                         owner_pid=12345, owner_start_time="old")
        from dispatch import work_lock
        work_lock.acquire(self.root, self.task_id, holder_agent="composer", route="supervisor",
                          assignment_id=self.assignment_id, run_id=state.run_id, resume=True)
        state.logical_task_id = self.task_id
        save_run_state(self.root, state)
        try_acquire_concurrency(self.root, assignment_id=self.assignment_id,
                                run_id=state.run_id, holder="test")
        return state

    def test_dead_prelaunch_owner_recovers_and_launches(self):
        self.queued()
        with patch("orchestrator.supervisor.pid_is_alive", return_value=False):
            self.assertEqual(self.tick()["process_state"], "completed")
        old = load_run_state(self.root, "abandoned")
        self.assertEqual(old.process_state, "failed_launch")
        self.assertIn("builder layer exited before launch", old.blocked_reason)
        self.assertFalse(has_assignment_lease(self.root, self.assignment_id))

    def test_live_or_unknown_prelaunch_owner_untouched(self):
        self.queued()
        for alive in (True, None):
            with patch("orchestrator.supervisor.pid_is_alive", return_value=alive):
                self.assertEqual(recover_orphans(self.root), [])
            self.assertTrue(has_assignment_lease(self.root, self.assignment_id))

    def test_capacity_creates_no_run_ids_or_directories(self):
        try_acquire_concurrency(self.root, assignment_id="live-other", run_id="live", holder="test")
        with patch("orchestrator.supervisor.generate_run_id") as generate:
            for _ in range(10):
                self.tick()
                self.clock.advance(seconds=1)
            generate.assert_not_called()
        self.assertEqual(self._runs(), [])
        wake = json.loads(self.wake_path.read_text())
        self.assertTrue(wake["retry"]["next_attempt_at"])
        self.assertEqual(wake["retry"].get("attempts", 0), 0)
        release_lease(self.root, "live-other")
        self.clock.advance(seconds=30)
        self.assertEqual(self.tick()["process_state"], "completed")

    def test_recovered_wake_has_bounded_retry(self):
        state = self.queued()
        state.wake_signal_path = str(self.wake_path)
        save_run_state(self.root, state)
        with patch("orchestrator.supervisor.pid_is_alive", return_value=False):
            self.tick()
        wake = json.loads(self.wake_path.read_text())
        self.assertEqual(wake["retry"]["attempts"], 1)
        self.assertTrue(wake["retry"]["next_attempt_at"])
        self.clock.advance(seconds=30)
        self.assertEqual(self.tick()["process_state"], "completed")

    def test_dead_owner_does_not_override_live_run_pid(self):
        state = self.queued()
        state.pid = 4242
        state.process_start_time = "live"
        save_run_state(self.root, state)
        with patch("orchestrator.supervisor.pid_is_alive", side_effect=lambda pid, start: pid == 4242):
            self.assertEqual(recover_orphans(self.root), [])
        self.assertTrue(has_assignment_lease(self.root, self.assignment_id))

    def test_recovery_cannot_release_replacement_lease_or_lock(self):
        from dispatch import work_lock
        state = self.queued()
        release_lease(self.root, self.assignment_id)
        try_acquire_concurrency(self.root, assignment_id=self.assignment_id, run_id="replacement", holder="test")
        work_lock.supersede(self.root, self.task_id, actor="test", reason="replacement",
                            holder_agent="composer", route="test",
                            assignment_id=self.assignment_id, run_id="replacement")
        state.logical_task_id = self.task_id
        # Keep initial evidence from before the new work lock was acquired.
        path = self.root / "runtime/dispatch/runs/abandoned/supervisor_run.json"
        path.write_text(json.dumps(state.to_dict()))
        with patch("orchestrator.supervisor.pid_is_alive", return_value=False):
            recover_orphans(self.root)
        self.assertEqual(work_lock.status(self.root)[0]["run_id"], "replacement")
        self.assertTrue(has_assignment_lease(self.root, self.assignment_id))
        self.assertEqual(load_run_state(self.root, "abandoned").process_state, "failed_launch")

    def test_condition_retry_capacity_does_not_spend_attempt(self):
        process_once(self.root, config=self._config(), popen=self._popen,
                     launch_plan_builder=self._plan, monitor=_monitor("quota exceeded"))
        source = self._runs()[0]
        self.clock.advance(minutes=15)
        try_acquire_concurrency(self.root, assignment_id="other", run_id="live", holder="test")
        for _ in range(3):
            self.tick()
            self.clock.advance(seconds=10)
        source = load_run_state(self.root, source.run_id)
        self.assertEqual(source.attempts, 0)
        self.assertIsNone(source.condition_retry_dispatched_at)
        self.assertEqual(len(self._runs()), 1)
        release_lease(self.root, "other")
        self.assertEqual(self.tick()["process_state"], "completed")


from orchestrator.agent_launcher import probe_version, _VERSION_CACHE
from orchestrator.process_ownership import owned_popen, terminate_owned, process_start_time


class VersionProbeTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows cmd descendant regression")
    def test_cmd_grandchild_timeout_leaves_decoy_alive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "child.json"
            child = root / "child.py"
            child.write_text("import subprocess,sys,time,json; from pathlib import Path; "
                             "p=subprocess.Popen([sys.executable,'-c',"
                             "\"import time; print('holding stdout', flush=True); time.sleep(300)\"]); "
                             f"Path({str(marker)!r}).write_text(json.dumps(p.pid)); time.sleep(300)")
            shim = root / "probe.cmd"
            shim.write_text(f'@echo off\n"{sys.executable}" "{child}"\n')
            decoy = owned_popen([sys.executable, "-c", "import time; time.sleep(300)"])
            try:
                start = time.monotonic()
                with patch("orchestrator.layer_heartbeat.tick") as heartbeat:
                    self.assertEqual(probe_version(str(shim), timeout=3), "unknown")
                self.assertLess(time.monotonic() - start, 7)
                self.assertGreaterEqual(heartbeat.call_count, 2)
                self.assertTrue(marker.exists())
                pid = json.loads(marker.read_text())
                self.assertIsNone(process_start_time(pid))
                self.assertIsNone(decoy.poll())
            finally:
                terminate_owned(decoy)
                decoy.wait(timeout=5)

    def test_cache_invalidated_by_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fake.exe"
            path.write_text("v1")
            _VERSION_CACHE[(str(path.resolve()), path.stat().st_mtime_ns)] = "cached"
            with patch("orchestrator.process_ownership.owned_popen", side_effect=OSError("unavailable")) as spawn:
                self.assertEqual(probe_version(str(path)), "cached")
                spawn.assert_not_called()
                path.write_text("new version")
                os.utime(path, ns=(1, 2))
                self.assertEqual(probe_version(str(path)), "unknown")
                spawn.assert_called_once()
