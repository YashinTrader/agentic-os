"""Control-plane regressions using only processes started by this test."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from dispatch.atomic_io import atomic_write_json
from orchestrator.layer_heartbeat import read_heartbeat
from orchestrator.process_ownership import owned_popen, terminate_owned, process_start_time
from orchestrator.supervisor_control import control_dir, identity_state, force_recorded_tree
from scripts.stop_supervisor import stop

ROOT = Path(__file__).resolve().parents[1]
FAKE = """import time
from orchestrator.layer_heartbeat import tick, install_stop_handlers
install_stop_handlers()
while True:
    tick()
    time.sleep(.05)
"""
HOST = """import sys
from pathlib import Path
from orchestrator.layer_supervisor import LayerSupervisor
from scripts import run_supervisor_layers as entrypoint
root = Path(sys.argv[1])
command = [sys.executable, str(root / 'fake.py')]
entrypoint.LayerSupervisor = lambda root, commands: LayerSupervisor(root, {'builder': command, 'claude': command})
sys.argv = ['run_supervisor_layers.py', '--state-root', str(root)]
raise SystemExit(entrypoint.main())
"""


class StopSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "runtime").mkdir()
        (self.root / "fake.py").write_text(FAKE, encoding="utf-8")
        self.env = {**os.environ, "PYTHONPATH": str(ROOT), "AGENTIC_OS_CONFIG_ROOT": str(ROOT)}
        self.processes = []
        self.addCleanup(self.cleanup_processes)

    def cleanup_processes(self):
        for process in reversed(self.processes):
            terminate_owned(process)
            process.wait(timeout=10)
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()

    def launch(self, command):
        options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {}
        process = owned_popen(command, cwd=ROOT, env=self.env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options)
        self.processes.append(process)
        return process

    def status(self):
        return read_heartbeat(control_dir(self.root) / "status.json")

    def wait_for(self, predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = predicate()
            if result:
                return result
            time.sleep(.05)
        self.fail(f"timed out; status={self.status()}")

    def start(self, version="old", unresponsive=False):
        host = self.root / f"{version}.py"
        prefix = ""
        if unresponsive:
            prefix = ("import orchestrator.layer_supervisor as module\n"
                      "original = module.read_heartbeat\n"
                      "module.read_heartbeat = lambda path: {} if path.name == 'stop_request.json' else original(path)\n")
        host.write_text(prefix + HOST, encoding="utf-8")
        process = self.launch([sys.executable, str(host), str(self.root)])
        def ticking():
            status = self.status()
            children = status.get("children", {})
            return (status.get("state") == "running" and len(children) == 2
                    and all(child.get("ticking") for child in children.values()))
        self.wait_for(ticking)
        return process

    def assert_gone(self, status):
        for record in [status, *status["recorded_children"]]:
            self.assertEqual(identity_state(record), "gone", record)

    def stop_cli(self, *extra):
        return subprocess.run([sys.executable, str(ROOT / "scripts/stop_supervisor.py"),
                               "--state-root", str(self.root), "--actor", "test", "--reason", "maintenance",
                               "--timeout", "10", *extra], env=self.env, capture_output=True, text=True, timeout=20)

    def legacy_status(self):
        record = {"state": "running", "children": {}, "state_root": str(self.root),
                  "config_root": str(ROOT), "config_root_git_sha": "old", "updated_at": "old"}
        atomic_write_json(control_dir(self.root) / "status.json", record)
        return record

    def test_legacy_adoption_archives_audits_and_allows_start(self):
        before = self.legacy_status()
        host = self.root / "blocked.py"
        host.write_text(HOST, encoding="utf-8")
        blocked = self.launch([sys.executable, str(host), str(self.root)])
        self.assertEqual(blocked.wait(timeout=10), 2)
        self.assertIn("--adopt-legacy-status", blocked.stdout.read().decode())
        result = self.stop_cli("--adopt-legacy-status")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        archives = list((control_dir(self.root) / "legacy").glob("status.*.json"))
        self.assertEqual(len(archives), 1)
        self.assertEqual(read_heartbeat(archives[0]), before)
        audit = read_heartbeat(next((control_dir(self.root) / "audit").glob("*.json")))
        self.assertEqual(audit["exit_code"], 0)
        self.assertEqual(audit["process_blockers"], [])
        self.assertEqual(audit["archive"], str(archives[0]))
        process = self.start()
        self.assertEqual(self.stop_cli().returncode, 0)
        self.assertEqual(process.wait(timeout=5), 0)

    def test_legacy_adoption_refuses_own_fake_runtime(self):
        before = self.legacy_status()
        fake = self.root / "run_orchestrator.py"
        fake.write_text("import time; time.sleep(120)", encoding="utf-8")
        process = self.launch([sys.executable, str(fake), "--state-root", str(self.root)])
        result = self.stop_cli("--adopt-legacy-status")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(str(process.pid), result.stdout)
        self.assertEqual(self.status(), before)
        self.assertFalse((control_dir(self.root) / "legacy").exists())
        self.assertIsNone(process.poll())
        terminate_owned(process)
        process.wait(timeout=10)

    def test_adoption_refuses_partial_identity_and_scan_errors(self):
        for field in ("pid", "process_start_time", "instance_token", "process_identity"):
            self.legacy_status()
            atomic_write_json(control_dir(self.root) / "status.json", {**self.status(), field: None})
            self.assertEqual(self.stop_cli("--adopt-legacy-status").returncode, 2)
        self.legacy_status()
        from scripts.stop_supervisor import adopt_legacy_status
        with patch("scripts.stop_supervisor.legacy_process_blockers", side_effect=OSError("unreadable")):
            self.assertEqual(adopt_legacy_status(self.root, "test", "scan error"), 2)
        self.assertTrue(self.status())

    def test_scan_resolves_root_flags_environment_and_cwd(self):
        from types import SimpleNamespace
        from orchestrator.supervisor_control import legacy_process_blockers
        for args, env, expected in (
            (["--state-root", str(self.root)], {}, True),
            (["--state-root=" + str(self.root)], {}, True),
            (["--root", "."], {}, True),
            ([], {"AGENTIC_OS_STATE_ROOT": str(self.root)}, True),
            (["--state-root", str(self.root / "other")], {}, False),
            ([], {}, True),
        ):
            process = SimpleNamespace(pid=123, info={"name": "python"},
                cmdline=lambda: [sys.executable, "run_orchestrator.py", *args],
                cwd=lambda: str(self.root), environ=lambda: env)
            with patch("psutil.process_iter", return_value=[process]):
                self.assertEqual(bool(legacy_process_blockers(self.root)), expected)

    def test_gone_identity_allows_start_without_adoption(self):
        process = self.launch([sys.executable, "-c", "pass"])
        process.wait(timeout=10)
        atomic_write_json(control_dir(self.root) / "status.json", {
            "pid": process.pid, "process_start_time": "previous-creation"})
        self.assertEqual(identity_state(self.status()), "gone")
        replacement = self.start()
        self.assertEqual(self.stop_cli().returncode, 0)
        self.assertEqual(replacement.wait(timeout=5), 0)

    def test_graceful_real_two_layers_and_audit(self):
        process = self.start()
        before = self.status()
        for child in before["children"].values():
            self.assertIn({"pid": child["heartbeat_pid"],
                           "process_start_time": child["heartbeat_process_start_time"]},
                          before["recorded_children"])
        result = self.stop_cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(process.wait(timeout=5), 0)
        self.assert_gone(before)
        status = self.status()
        self.assertEqual(status["state"], "stopped_by_request")
        request = read_heartbeat(control_dir(self.root) / "stop_request.json")
        for key in ("requester", "reason", "token", "at"):
            self.assertTrue(request[key])
        audit = read_heartbeat(control_dir(self.root) / "audit" / f"{request['token']}.json")
        self.assertEqual(audit["exit_code"], 0)
        self.assertEqual(audit["request"], request)

    def test_unresponsive_forces_only_recorded_tree_leaves_decoy(self):
        process = self.start(unresponsive=True)
        decoy = self.launch([sys.executable, "-c", "import time; time.sleep(120)"])
        record = self.status()
        result = self.stop_cli("--timeout", ".1")
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("forced-owned", result.stdout)
        process.wait(timeout=5)
        self.assert_gone(record)
        self.assertIsNone(decoy.poll())
        audit = list((control_dir(self.root) / "audit").glob("*.json"))
        self.assertTrue(json.loads(audit[0].read_text())["forced"])

    def test_reused_pid_refused_without_signaling(self):
        process = self.launch([sys.executable, "-c", "import time; time.sleep(120)"])
        atomic_write_json(control_dir(self.root) / "status.json", {
            "pid": process.pid, "process_start_time": "different-creation-time"})
        with patch("scripts.stop_supervisor.force_recorded_tree") as force:
            self.assertEqual(stop(self.root, "test", "reuse", 0), 2)
            force.assert_not_called()
        self.assertIsNone(process.poll())

    def test_force_revalidates_creation_immediately_before_termination(self):
        process = self.start()
        record = self.status()
        record["process_start_time"] = "reused"
        with self.assertRaises(ValueError):
            force_recorded_tree(record)
        self.assertIsNone(process.poll())
        self.assertEqual(self.stop_cli().returncode, 0)
        self.assertEqual(process.wait(timeout=5), 0)

    @unittest.skipUnless(os.name == "nt", "Windows Job membership fence")
    def test_foreign_job_is_refused_and_decoy_survives(self):
        from orchestrator.process_ownership import ownership_metadata
        process = self.start()
        decoy = self.launch([sys.executable, "-c", "import time; time.sleep(120)"])
        record = {**self.status(), **ownership_metadata(decoy)}
        # Keep the real root's start time; only the Job name is foreign.
        record["process_start_time"] = self.status()["process_start_time"]
        with self.assertRaises(ValueError):
            force_recorded_tree(record)
        self.assertIsNone(process.poll())
        self.assertIsNone(decoy.poll())
        self.assertEqual(self.stop_cli().returncode, 0)
        self.assertEqual(process.wait(timeout=5), 0)

    def test_maintenance_entrypoint_and_resume(self):
        self.assertEqual(stop(self.root, "test", "cleanup", maintenance="on", request_stop=False), 0)
        result = subprocess.run([sys.executable, str(ROOT / "scripts/run_supervisor_layers.py"),
                                 "--state-root", str(self.root)], env=self.env, capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("maintenance mode", result.stdout)
        self.assertFalse(self.status())
        self.assertEqual(stop(self.root, "test", "resume", maintenance="off", request_stop=False), 0)
        process = self.start()
        self.assertEqual(self.stop_cli().returncode, 0)
        self.assertEqual(process.wait(timeout=5), 0)

    def test_live_status_fence_even_without_instance_lock(self):
        process = self.launch([sys.executable, "-c", "import time; time.sleep(120)"])
        atomic_write_json(control_dir(self.root) / "status.json", {
            "pid": process.pid, "process_start_time": process_start_time(process.pid)})
        host = self.root / "second.py"
        host.write_text(HOST, encoding="utf-8")
        second = self.launch([sys.executable, str(host), str(self.root)])
        self.assertEqual(second.wait(timeout=10), 2)
        self.assertIsNone(process.poll())

    def test_restart_rollback_no_overlap_and_heartbeats_resume(self):
        for version in ("old", "new", "old"):
            process = self.start(version)
            before = self.status()
            second = self.launch([sys.executable, str(self.root / f"{version}.py"), str(self.root)])
            self.assertEqual(second.wait(timeout=10), 2)
            self.assertEqual(self.status()["pid"], before["pid"])
            for previous in self.processes:
                if previous is not process:
                    self.assertIsNotNone(previous.poll())
            self.assertEqual(self.stop_cli().returncode, 0)
            self.assertEqual(process.wait(timeout=5), 0)
            self.assert_gone(before)

    def test_stale_stop_request_does_not_stop_replacement(self):
        process = self.start()
        atomic_write_json(control_dir(self.root) / "stop_request.json", {
            "instance_token": "old-instance", "requester": "test", "reason": "stale",
            "token": "old-request", "at": "yesterday"})
        time.sleep(.6)
        self.assertIsNone(process.poll())
        self.assertEqual(self.stop_cli("--maintenance", "on").returncode, 0)
        self.assertEqual(process.wait(timeout=5), 0)
        self.assertTrue((control_dir(self.root) / "maintenance.json").exists())


if __name__ == "__main__":
    unittest.main()
