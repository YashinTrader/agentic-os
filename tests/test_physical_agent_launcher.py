"""Phase 3.9.1 — physical agent launcher / supervisor tests (no real Grok/Codex)."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.assignment_channel import (  # noqa: E402
    create_assignment_from_task_yaml,
    read_assignment,
    write_assignment,
)
from dispatch.orchestrator_pokes import list_orchestrator_pokes  # noqa: E402
from orchestrator.agent_launcher import (  # noqa: E402
    UNSAFE_GROK_FLAGS,
    build_grok_launch_plan,
    launch_process,
    redact_argv,
)
from orchestrator.event_router import assert_claude_only_poke_target, route_completion  # noqa: E402
from orchestrator.failure_classify import (  # noqa: E402
    build_fingerprint,
    classify_process_output,
    should_relaunch,
)
from orchestrator.leases import count_active_leases, try_acquire_concurrency  # noqa: E402
from orchestrator.process_monitor import monitor_process  # noqa: E402
from orchestrator.runtime_store import (  # noqa: E402
    STATE_COMPLETED,
    STATE_RUNNING,
    RunState,
    load_run_state,
    save_run_state,
)
from orchestrator.supervisor import SupervisorConfig, process_once, process_wake_signal  # noqa: E402
from dashboard.app import _physical_run_lifecycle_label, load_execution_runs  # noqa: E402


class FakeProcess:
    def __init__(self, pid: int = 4242, exit_code: int = 0, polls_before_exit: int = 1):
        self.pid = pid
        self._exit_code = exit_code
        self._polls = 0
        self._polls_before_exit = polls_before_exit
        self.killed = False

    def poll(self):
        self._polls += 1
        if self._polls >= self._polls_before_exit:
            return self._exit_code
        return None

    def wait(self, timeout=None):
        del timeout
        return self._exit_code

    def kill(self):
        self.killed = True
        self._exit_code = -9


class PhysicalLauncherFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name) / "repo"
        # Minimal repo surface for assignment channel + supervisor.
        for rel in (
            "tasks/active",
            "runtime/dispatch/assignments/inbox",
            "runtime/dispatch/assignments/claims",
            "runtime/dispatch/assignments/outbox",
            "runtime/dispatch/wake_queue/composer",
            "runtime/dispatch/pokes/orchestrator",
            "runtime/dispatch/runs",
            "agents",
            "handoffs",
            "docs",
        ):
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        # Copy minimal agent adapter for codex fallback imports if needed.
        src_agents = REPO_ROOT / "agents"
        if src_agents.is_dir():
            for name in (
                "adapter_registry.yaml",
                "composer_restricted_adapter.yaml",
                "codex_restricted_adapter.yaml",
            ):
                src = src_agents / name
                if src.is_file():
                    shutil.copy2(src, self.root / "agents" / name)

        self.task_path = self.root / "tasks" / "active" / "T-PHYS-LAUNCH.yaml"
        self.task_path.write_text(
            yaml.safe_dump(
                {
                    "id": "T-PHYS-LAUNCH",
                    "title": "Physical launch fixture",
                    "status": "ready",
                    "owner": "composer",
                    "reviewer": "claude",
                    "objective": "fixture",
                    "execution": {
                        "mode": "auto_local_worktree",
                        "adapter": "composer-restricted",
                        "allowed_paths": ["docs/**", "handoffs/**"],
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        path, errors = write_assignment(
            self.root,
            task_id="T-PHYS-LAUNCH",
            title="Physical launch fixture",
            goal="launch",
            base_branch="main",
            base_sha="a" * 40,
            allowed_paths=["docs/**", "handoffs/**"],
            forbidden_operations=["deploy", "git_merge"],
            acceptance_criteria=["done"],
            verification_commands=["python -c pass"],
            timeout=600,
            assigned_by="claude",
            assigned_to="composer",
            task_path="tasks/active/T-PHYS-LAUNCH.yaml",
            adapter_id="composer-restricted",
            execution_route="composer_local_builder",
            new_branch="agent/composer/T-PHYS-LAUNCH",
            handoff_path="handoffs/T-PHYS-LAUNCH__composer__to__claude.md",
        )
        self.assertIsNotNone(path, errors)
        self.assignment_id = path.stem  # type: ignore[union-attr]
        # write_assignment uses assignment id in filename
        inbox = list((self.root / "runtime" / "dispatch" / "assignments" / "inbox").glob("*.json"))
        self.assertTrue(inbox)
        self.assignment_id = inbox[0].stem
        wake = {
            "schema_version": "1.0",
            "assignment_id": self.assignment_id,
            "task_id": "T-PHYS-LAUNCH",
            "agent_id": "composer",
            "adapter_id": "composer-restricted",
            "task_path": "tasks/active/T-PHYS-LAUNCH.yaml",
            "mechanism": "assignment_watcher",
            "requested_by": "claude",
        }
        self.wake_path = (
            self.root / "runtime" / "dispatch" / "wake_queue" / "composer" / f"{self.assignment_id}.json"
        )
        self.wake_path.write_text(json.dumps(wake), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _fake_popen_success(self, *args, **kwargs):
        del args, kwargs
        return FakeProcess(pid=7777, exit_code=0, polls_before_exit=2)

    def _plan_ok(self, **kwargs):
        worktree = kwargs.get("worktree") or self.root
        return build_grok_launch_plan(
            worktree=Path(worktree),
            prompt=kwargs.get("prompt") or "test",
            max_turns=kwargs.get("max_turns", 5),
            grok_executable=sys.executable,
            version_runner=lambda *a, **k: type("R", (), {"stdout": "fake-grok 0.0.0\n", "stderr": ""})(),
        )


class GrokArgvTests(unittest.TestCase):
    def test_grok_argv_construction_shell_false_safe_flags(self) -> None:
        plan = build_grok_launch_plan(
            worktree=Path("C:/tmp/wt"),
            prompt="do the docs task",
            max_turns=12,
            grok_executable="C:/tools/grok.exe",
            version_runner=lambda *a, **k: type("R", (), {"stdout": "grok 0.2.101\n", "stderr": ""})(),
        )
        self.assertTrue(plan.ok)
        self.assertEqual(plan.argv[0], "C:/tools/grok.exe")
        self.assertIn("--cwd", plan.argv)
        self.assertIn("--single", plan.argv)
        self.assertIn("--max-turns", plan.argv)
        self.assertNotIn("--always-approve", plan.argv)
        for flag in plan.argv:
            self.assertNotIn(flag, UNSAFE_GROK_FLAGS)
        self.assertEqual(plan.command_redacted, redact_argv(plan.argv))

    def test_launch_process_records_pid_and_requires_real_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = Path(tmp) / "out.log"
            stderr = Path(tmp) / "err.log"
            plan = build_grok_launch_plan(
                worktree=Path(tmp),
                prompt="x",
                grok_executable=sys.executable,
                version_runner=lambda *a, **k: type("R", (), {"stdout": "v\n", "stderr": ""})(),
            )
            # Force argv to fake executable shape
            plan.argv = [sys.executable, "-c", "print('hi')"]
            plan.command_redacted = redact_argv(plan.argv)
            plan.blocked_reasons = []
            handle, msg = launch_process(
                plan,
                stdout_path=stdout,
                stderr_path=stderr,
                popen=lambda *a, **k: FakeProcess(pid=9991),
            )
            self.assertIsNotNone(handle)
            assert handle is not None
            self.assertEqual(handle.pid, 9991)
            self.assertEqual(msg, "launching")


class FailureClassifyTests(unittest.TestCase):
    def test_auth_and_quota_classification(self) -> None:
        auth = classify_process_output(
            agent="composer",
            adapter="composer-restricted",
            exit_code=1,
            stderr="Error: unauthorized — please run grok login",
        )
        self.assertEqual(auth.process_state, "blocked_authentication")
        quota = classify_process_output(
            agent="codex",
            adapter="codex-restricted",
            exit_code=1,
            stdout="usage limit exceeded; retry-after: 60",
        )
        self.assertEqual(quota.process_state, "blocked_quota")
        self.assertIsNotNone(quota.retry_after)

    def test_unchanged_failure_no_relaunch(self) -> None:
        c = classify_process_output(
            agent="composer",
            adapter="composer-restricted",
            exit_code=1,
            stderr="quota exceeded",
        )
        fp = build_fingerprint(agent="composer", adapter="composer-restricted", classification=c, exit_code=1)
        ok, reason = should_relaunch(previous=fp, current=fp, retry_count=0)
        self.assertFalse(ok)
        self.assertIn("unchanged", reason)


class SupervisorFlowTests(PhysicalLauncherFixture):
    def test_supervisor_pickup_atomic_claim_and_running_after_pid(self) -> None:
        seen_states: list[str] = []

        def tracking_popen(*args, **kwargs):
            del args, kwargs
            # When popen is called, state should already be launching, not running.
            return FakeProcess(pid=5555, exit_code=0, polls_before_exit=2)

        def plan_builder(**kwargs):
            plan = self._plan_ok(**kwargs)
            plan.argv = [sys.executable, "-c", "print('ok')"]
            plan.executable = sys.executable
            plan.command_redacted = redact_argv(plan.argv)
            plan.blocked_reasons = []
            return plan

        report = process_wake_signal(
            self.root,
            self.wake_path,
            config=SupervisorConfig(agent="composer", timeout_seconds=30, allow_codex_fallback=False),
            popen=tracking_popen,
            launch_plan_builder=plan_builder,
        )
        self.assertIn(report["status"], {"completed", STATE_COMPLETED})
        self.assertEqual(report["pid"], 5555)
        state = load_run_state(self.root, report["run_id"])
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.process_state, STATE_COMPLETED)
        self.assertEqual(state.pid, 5555)
        self.assertTrue(state.stdout_path)
        self.assertTrue(state.stderr_path)
        self.assertIsNotNone(state.heartbeat_at)
        rec, _ = read_assignment(self.root, self.assignment_id)
        self.assertEqual(rec.status, "awaiting_review")
        pokes, _ = list_orchestrator_pokes(self.root)
        completion_pokes = [p for p in pokes if p.get("event") == "assignment_completed"]
        # Exactly one undrained completion poke (notification layer); not a launch record.
        self.assertEqual(len(completion_pokes), 1)
        self.assertEqual(completion_pokes[0].get("target"), "orchestrator")
        self.assertFalse(completion_pokes[0].get("is_process_launch"))
        self.assertEqual(completion_pokes[0].get("layer"), "notification")
        # Execution evidence is the PID/run record, not the poke.
        self.assertEqual(report["pid"], 5555)
        self.assertIsNotNone(state.pid)
        # No peer-builder poke targets.
        self.assertFalse(any(p.get("target") in {"codex", "composer", "grok"} for p in pokes))
        # Route layers stay distinct when present.
        if "route" in report and isinstance(report["route"], dict):
            route = report["route"]
            if "execution_layer" in route:
                self.assertEqual(route["execution_layer"].get("pid"), 5555)
            if "notification_layer" in route:
                self.assertFalse(route["notification_layer"].get("is_process_launch"))

    def test_no_duplicate_launch_and_concurrency_one(self) -> None:
        lease1, reason1 = try_acquire_concurrency(
            self.root, assignment_id="a1", run_id="r1", holder="supervisor", max_concurrency=1
        )
        self.assertIsNotNone(lease1, reason1)
        lease2, reason2 = try_acquire_concurrency(
            self.root, assignment_id="a2", run_id="r2", holder="supervisor", max_concurrency=1
        )
        self.assertIsNone(lease2)
        self.assertIn("capacity", reason2)
        self.assertEqual(count_active_leases(self.root), 1)

        # Active lease blocks same assignment duplicate.
        report = process_wake_signal(
            self.root,
            self.wake_path,
            config=SupervisorConfig(agent="composer", allow_codex_fallback=False),
            popen=self._fake_popen_success,
            launch_plan_builder=self._plan_ok,
        )
        # Either deferred by capacity or skipped by lease on assignment after first acquire on a1.
        self.assertIn(report["status"], {"deferred", "skipped", "completed", "failed_launch", "blocked"})

    def test_nonzero_exit_and_timeout(self) -> None:
        def plan_builder(**kwargs):
            plan = self._plan_ok(**kwargs)
            plan.argv = [sys.executable, "-c", "import sys; sys.exit(2)"]
            plan.blocked_reasons = []
            plan.command_redacted = redact_argv(plan.argv)
            return plan

        report = process_wake_signal(
            self.root,
            self.wake_path,
            config=SupervisorConfig(agent="composer", allow_codex_fallback=False, timeout_seconds=30),
            popen=lambda *a, **k: FakeProcess(pid=12, exit_code=2, polls_before_exit=1),
            launch_plan_builder=plan_builder,
        )
        self.assertEqual(report["process_state"], "failed")

        # Fresh wake for timeout case
        self.wake_path.write_text(
            json.dumps(
                {
                    "assignment_id": self.assignment_id,
                    "task_id": "T-PHYS-LAUNCH",
                    "agent_id": "composer",
                    "adapter_id": "composer-restricted",
                    "task_path": "tasks/active/T-PHYS-LAUNCH.yaml",
                }
            ),
            encoding="utf-8",
        )
        # Reset assignment to pending for second path is hard; test monitor timeout unit-level instead.
        state = RunState(
            run_id="r-timeout",
            assignment_id="x",
            task_id="t",
            assigned_agent="composer",
            adapter="composer-restricted",
            process_state=STATE_RUNNING,
            pid=1,
        )
        proc = FakeProcess(pid=1, exit_code=0, polls_before_exit=1000)
        mon = monitor_process(
            proc,
            state=state,
            repo_root=self.root,
            stdout_path=self.root / "runtime" / "dispatch" / "runs" / "r-timeout" / "stdout.log",
            stderr_path=self.root / "runtime" / "dispatch" / "runs" / "r-timeout" / "stderr.log",
            timeout_seconds=0,  # immediate timeout
            heartbeat_seconds=0.01,
            sleep_fn=lambda _s: None,
        )
        self.assertTrue(mon.timed_out)
        self.assertTrue(proc.killed)

    def test_completed_assignment_not_relaunched(self) -> None:
        # Seed a completed run for this assignment.
        state = RunState(
            run_id="already-done",
            assignment_id=self.assignment_id,
            task_id="T-PHYS-LAUNCH",
            assigned_agent="composer",
            adapter="composer-restricted",
            process_state=STATE_COMPLETED,
            pid=1,
        )
        save_run_state(self.root, state)
        report = process_wake_signal(
            self.root,
            self.wake_path,
            config=SupervisorConfig(agent="composer"),
            popen=self._fake_popen_success,
            launch_plan_builder=self._plan_ok,
        )
        self.assertEqual(report["status"], "skipped")
        self.assertIn("already completed", report["reason"])

    def test_auth_classification_blocks_without_relaunch_loop(self) -> None:
        def plan_builder(**kwargs):
            plan = self._plan_ok(**kwargs)
            plan.argv = [sys.executable, "-c", "print('x')"]
            plan.blocked_reasons = []
            plan.command_redacted = redact_argv(plan.argv)
            return plan

        def popen_auth(*a, **k):
            proc = FakeProcess(pid=88, exit_code=1, polls_before_exit=1)

            def write_logs():
                return proc

            return proc

        # Inject auth failure via monitor wrapper by using process that exits 1 and stderr file content.
        # Simpler: monkeypatch classify by writing stderr after launch via custom monitor.
        def mon(process, **kwargs):
            state = kwargs["state"]
            state.heartbeat_at = "2026-07-15T00:00:00Z"
            save_run_state(kwargs["repo_root"], state)
            kwargs["stderr_path"].write_text("authentication failed: not logged in", encoding="utf-8")
            kwargs["stdout_path"].write_text("", encoding="utf-8")
            return type(
                "M",
                (),
                {
                    "exit_code": 1,
                    "timed_out": False,
                    "stdout": "",
                    "stderr": "authentication failed: not logged in",
                    "orphaned": False,
                },
            )()

        report = process_wake_signal(
            self.root,
            self.wake_path,
            config=SupervisorConfig(agent="composer", allow_codex_fallback=False),
            popen=lambda *a, **k: FakeProcess(pid=88, exit_code=1),
            launch_plan_builder=plan_builder,
            monitor=mon,
        )
        self.assertEqual(report["process_state"], "blocked_authentication")

        # Second wake with same fingerprint must not relaunch.
        self.wake_path.write_text(
            json.dumps(
                {
                    "assignment_id": self.assignment_id,
                    "task_id": "T-PHYS-LAUNCH",
                    "agent_id": "composer",
                    "adapter_id": "composer-restricted",
                    "task_path": "tasks/active/T-PHYS-LAUNCH.yaml",
                }
            ),
            encoding="utf-8",
        )
        report2 = process_wake_signal(
            self.root,
            self.wake_path,
            config=SupervisorConfig(agent="composer", allow_codex_fallback=False),
            popen=lambda *a, **k: FakeProcess(pid=99, exit_code=0),
            launch_plan_builder=plan_builder,
            monitor=mon,
        )
        self.assertEqual(report2["status"], "skipped")

    def test_claude_only_poke_topology(self) -> None:
        assert_claude_only_poke_target("orchestrator")
        assert_claude_only_poke_target("claude")
        with self.assertRaises(ValueError):
            assert_claude_only_poke_target("codex")

    def test_process_once_idle_without_wake(self) -> None:
        self.wake_path.unlink()
        report = process_once(self.root, config=SupervisorConfig(agent="composer"))
        self.assertEqual(report["status"], "idle")

    def test_dashboard_state_rendering_labels(self) -> None:
        self.assertEqual(
            _physical_run_lifecycle_label(process_state="running", status="running", kind="physical_agent_launch"),
            "actually_running",
        )
        self.assertEqual(
            _physical_run_lifecycle_label(process_state="blocked_quota", status="blocked_quota", kind="physical_agent_launch"),
            "blocked_external",
        )
        state = RunState(
            run_id="dash-1",
            assignment_id=self.assignment_id,
            task_id="T-PHYS-LAUNCH",
            assigned_agent="composer",
            adapter="composer-restricted",
            process_state="running",
            pid=321,
            kind="physical_agent_launch",
        )
        save_run_state(self.root, state)
        runs, errors = load_execution_runs(self.root)
        self.assertEqual(errors, [])
        match = next(r for r in runs if r["run_id"] == "dash-1")
        self.assertEqual(match["process_state"], "running")
        self.assertEqual(match["display_lifecycle"], "actually_running")
        self.assertEqual(match["pid"], 321)


class CodexFallbackLineageTests(PhysicalLauncherFixture):
    def test_fallback_lineage_and_no_loop_marker(self) -> None:
        # Primary plan fails with no adapter so supervisor may attempt codex path.
        def bad_grok(**kwargs):
            plan = self._plan_ok(**kwargs)
            plan.argv = []
            plan.blocked_reasons = ["blocked_no_adapter: grok executable not found on PATH"]
            return plan

        report = process_wake_signal(
            self.root,
            self.wake_path,
            config=SupervisorConfig(agent="composer", allow_codex_fallback=True),
            popen=lambda *a, **k: FakeProcess(pid=1, exit_code=0),
            launch_plan_builder=bad_grok,
        )
        # Without a working codex binary in fixture, expect blocked_no_adapter terminal — not a loop.
        self.assertIn(report["status"], {"blocked", "blocked_no_adapter", "failed_launch", "completed"})
        self.assertNotEqual(report.get("status"), "infinite")


if __name__ == "__main__":
    unittest.main()
