"""Bounded builder condition retry. Fake clocks, probes, and processes only."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch import work_lock  # noqa: E402
from dispatch.assignment_channel import write_assignment  # noqa: E402
from dispatch.orchestrator_pokes import list_orchestrator_pokes  # noqa: E402
from orchestrator.agent_launcher import build_grok_launch_plan, redact_argv  # noqa: E402
from orchestrator.builder_condition import (  # noqa: E402
    backoff_seconds,
    default_builder_probe,
    schedule_next_eligible,
)
from orchestrator.failure_classify import classify_process_output  # noqa: E402
from orchestrator.runtime_store import list_supervisor_runs, load_run_state, save_run_state  # noqa: E402
from orchestrator.supervisor import SupervisorConfig, process_once  # noqa: E402


class Clock:
    def __init__(self) -> None:
        self.current = datetime(2026, 10, 21, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **delta: int) -> None:
        self.current = self.current + timedelta(**delta)


def _monitor(stderr: str, *, exit_code: int = 1, activity: int = 0):
    def monitor(process, **kwargs):
        del process
        state = kwargs["state"]
        if activity:
            state.activity_events = activity
        return SimpleNamespace(
            exit_code=exit_code,
            timed_out=False,
            stdout='{"type":"end","stopReason":"end_turn"}\n' if exit_code == 0 else "",
            stderr=stderr,
            orphaned=False,
            deadline_state=None,
        )

    return monitor


class ConditionRetryFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name) / "repo"
        self.worktree = Path(self.tmp.name) / "worktree"
        self.worktree.mkdir(parents=True)
        self.clock = Clock()
        self.prompts: list[str] = []
        self.task_id = "T-COND"
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
        src_agents = REPO_ROOT / "agents"
        for name in (
            "adapter_registry.yaml",
            "composer_restricted_adapter.yaml",
            "codex_restricted_adapter.yaml",
        ):
            src = src_agents / name
            if src.is_file():
                shutil.copy2(src, self.root / "agents" / name)
        task_path = self.root / "tasks" / "active" / "T-COND.yaml"
        task_path.write_text(
            yaml.safe_dump(
                {
                    "id": self.task_id,
                    "title": "Condition retry fixture",
                    "status": "ready",
                    "owner": "composer",
                    "reviewer": "claude",
                    "objective": "fixture",
                    "execution": {
                        "mode": "auto_local_worktree",
                        "adapter": "composer-restricted",
                        "allowed_paths": ["docs/**"],
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        path, errors = write_assignment(
            self.root,
            task_id=self.task_id,
            title="Condition retry fixture",
            goal="launch",
            base_branch="main",
            base_sha="a" * 40,
            allowed_paths=["docs/**"],
            forbidden_operations=["deploy", "git_merge"],
            acceptance_criteria=["done"],
            verification_commands=["python -c pass"],
            timeout=600,
            assigned_by="claude",
            assigned_to="composer",
            task_path="tasks/active/T-COND.yaml",
            adapter_id="composer-restricted",
            execution_route="composer_local_builder",
            new_branch="agent/composer/T-COND",
            handoff_path="handoffs/T-COND__composer__to__claude.md",
        )
        self.assertIsNotNone(path, errors)
        inbox = list((self.root / "runtime/dispatch/assignments/inbox").glob("*.json"))
        self.assignment_id = inbox[0].stem
        self.wake_path = (
            self.root / "runtime/dispatch/wake_queue" / "composer" / f"{self.assignment_id}.json"
        )
        self._write_wake()
        allocation = SimpleNamespace(
            success=True,
            errors=[],
            worktree_path=str(self.worktree),
            branch_name="agent/composer/T-COND",
        )
        self.allocator = patch("orchestrator.supervisor.allocate_worktree", return_value=allocation)
        self.allocator.start()

    def tearDown(self) -> None:
        self.allocator.stop()
        self.tmp.cleanup()

    def _write_wake(self) -> None:
        self.wake_path.parent.mkdir(parents=True, exist_ok=True)
        self.wake_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "assignment_id": self.assignment_id,
                    "task_id": self.task_id,
                    "agent_id": "composer",
                    "adapter_id": "composer-restricted",
                    "task_path": "tasks/active/T-COND.yaml",
                    "mechanism": "assignment_watcher",
                    "requested_by": "claude",
                }
            ),
            encoding="utf-8",
        )

    def _config(self, **overrides: object) -> SupervisorConfig:
        values = dict(
            agent="composer",
            allow_codex_fallback=False,
            timeout_seconds=30,
            now=self.clock,
        )
        values.update(overrides)
        return SupervisorConfig(**values)  # type: ignore[arg-type]

    def _plan(self, **kwargs):
        self.prompts.append(str(kwargs.get("prompt") or ""))
        plan = build_grok_launch_plan(
            worktree=Path(kwargs.get("worktree") or self.worktree),
            prompt=kwargs.get("prompt") or "test",
            max_turns=kwargs.get("max_turns", 5),
            grok_executable=sys.executable,
            version_runner=lambda *a, **k: SimpleNamespace(stdout="fake-grok 0.0.0\n", stderr=""),
        )
        plan.argv = [sys.executable, "-c", "print('ok')"]
        plan.executable = sys.executable
        plan.command_redacted = redact_argv(plan.argv)
        plan.blocked_reasons = []
        return plan

    def _popen(self, *args, **kwargs):
        del args, kwargs
        return SimpleNamespace(pid=4242)

    def _runs(self):
        return list_supervisor_runs(self.root, limit=20)

    def _poke_events(self) -> list[str]:
        pokes, errors = list_orchestrator_pokes(self.root)
        self.assertEqual(errors, [])
        return [str(poke.get("event")) for poke in pokes]


class QuotaBackoffTests(ConditionRetryFixture):
    def test_quota_without_retry_after_relaunches_once_after_backoff(self) -> None:
        monitor = _monitor("quota exceeded")
        with patch("orchestrator.process_ownership.owned_run") as spawned:
            first = process_once(
                self.root,
                config=self._config(),
                popen=self._popen,
                launch_plan_builder=self._plan,
                monitor=monitor,
            )
            self.assertEqual(first["process_state"], "blocked_quota", first)
            blocked = self._runs()[0]
            self.assertEqual(blocked.blocked_on, "quota:grok")
            self.assertEqual(blocked.attempts, 0)
            self.assertTrue(blocked.blocked_since)
            self.assertEqual(len(self._runs()), 1)

            self.clock.advance(minutes=14)
            self._write_wake()
            skipped = process_once(
                self.root,
                config=self._config(),
                popen=self._popen,
                launch_plan_builder=self._plan,
                monitor=monitor,
            )
            self.assertEqual(skipped["status"], "skipped", skipped)
            self.assertIn("unchanged", skipped["reason"])
            self.assertEqual(len(self._runs()), 1)

            self.clock.advance(minutes=1)
            queue = list((self.root / "runtime/dispatch/wake_queue/composer").glob("*.json"))
            self.assertEqual(queue, [])
            second = process_once(
                self.root,
                config=self._config(),
                popen=self._popen,
                launch_plan_builder=self._plan,
                monitor=monitor,
            )
            self.assertNotEqual(second.get("status"), "error", second)
            runs = self._runs()
            self.assertEqual(len(runs), 2)
            latest = runs[0]
            self.assertEqual(latest.worktree, blocked.worktree)
            self.assertEqual(latest.branch, blocked.branch)
            self.assertEqual(latest.attempts, 1)
            self.assertEqual(latest.blocked_on, "quota:grok")
            self.assertEqual(latest.blocked_since, blocked.blocked_since)
            self.assertNotEqual(latest.run_id, blocked.run_id)
            locks = work_lock.status(self.root, self.task_id)
            self.assertEqual(locks[0]["run_id"], latest.run_id)
            self.assertEqual(self._poke_events(), ["assignment_blocked_external", "assignment_blocked_external"])
            self.assertIn(blocked.run_id, self.prompts[-1])
            self.assertIn("Do not discard", self.prompts[-1])

            self.clock.advance(minutes=1)
            third = process_once(
                self.root,
                config=self._config(),
                popen=self._popen,
                launch_plan_builder=self._plan,
                monitor=monitor,
            )
            self.assertNotEqual(third.get("status"), "blocked_quota")
            self.assertEqual(len(self._runs()), 2)
            spawned.assert_not_called()

    def test_periodic_tick_relaunches_once_with_empty_wake_queue(self) -> None:
        """Backoff eligibility relaunches from the tick itself. No later wake."""
        monitor = _monitor("quota exceeded")
        kwargs = dict(popen=self._popen, launch_plan_builder=self._plan, monitor=monitor)
        with patch("orchestrator.process_ownership.owned_run") as spawned:
            first = process_once(self.root, config=self._config(), **kwargs)
            self.assertEqual(first["process_state"], "blocked_quota", first)
            blocked = self._runs()[0]
            fingerprint = blocked.failure_fingerprint or {}
            self.assertFalse(fingerprint.get("retry_after"))
            self.assertEqual(len(self._runs()), 1)
            self.assertEqual(len(self.prompts), 1)

            queue = self.root / "runtime" / "dispatch" / "wake_queue" / "composer"
            self.assertEqual(list(queue.glob("*.json")), [])

            self.clock.advance(minutes=15)
            self.assertEqual(list(queue.glob("*.json")), [])
            second = process_once(self.root, config=self._config(), **kwargs)
            self.assertNotEqual(second.get("status"), "error", second)
            self.assertNotEqual(second.get("status"), "skipped", second)
            self.assertEqual(len(self.prompts), 2)
            runs = self._runs()
            self.assertEqual(len(runs), 2)
            latest = runs[0]
            self.assertEqual(latest.condition_retry_from_run_id, blocked.run_id)
            self.assertNotEqual(latest.run_id, blocked.run_id)
            self.assertEqual(latest.worktree, blocked.worktree)
            self.assertEqual(latest.branch, blocked.branch)
            self.assertEqual(list(queue.glob("*.json")), [])

            held = process_once(self.root, config=self._config(), **kwargs)
            self.assertNotEqual(held.get("status"), "blocked_quota")
            self.assertEqual(len(self.prompts), 2)
            self.assertEqual(len(self._runs()), 2)
            self.assertEqual(list(queue.glob("*.json")), [])
            spawned.assert_not_called()


class ProbeEligibilityTests(ConditionRetryFixture):
    def test_probe_success_relaunches_early_and_rate_limit_holds(self) -> None:
        calls: list[datetime] = []

        def probe(blocked_on: str) -> bool:
            self.assertEqual(blocked_on, "quota:grok")
            calls.append(self.clock.current)
            return len(calls) > 1

        monitor = _monitor("quota exceeded")
        kwargs = dict(popen=self._popen, launch_plan_builder=self._plan, monitor=monitor)
        first = process_once(self.root, config=self._config(condition_probe=probe), **kwargs)
        self.assertEqual(first["process_state"], "blocked_quota")

        self.clock.advance(minutes=1)
        early = process_once(self.root, config=self._config(condition_probe=probe), **kwargs)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self._runs()), 1)
        self.assertNotEqual(early.get("status"), "blocked_quota")

        self.clock.advance(minutes=1)
        process_once(self.root, config=self._config(condition_probe=probe), **kwargs)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self._runs()), 1)

        self.clock.advance(minutes=9)
        launched = process_once(self.root, config=self._config(condition_probe=probe), **kwargs)
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(launched.get("status"), "error", launched)
        self.assertEqual(len(self._runs()), 2)


class RetryAfterTests(ConditionRetryFixture):
    def test_retry_after_is_honored_ahead_of_backoff(self) -> None:
        monitor = _monitor("quota exceeded; resets at 2026-10-21T04:00:00Z")
        kwargs = dict(popen=self._popen, launch_plan_builder=self._plan, monitor=monitor)
        first = process_once(self.root, config=self._config(), **kwargs)
        self.assertEqual(first["process_state"], "blocked_quota", first)
        blocked = self._runs()[0]
        self.assertTrue(str(blocked.next_eligible_at).startswith("2026-10-21T04:00:00"))

        self.clock.advance(minutes=15)
        process_once(self.root, config=self._config(), **kwargs)
        self.assertEqual(len(self._runs()), 1)

        self.clock.advance(hours=4)
        self.clock.current = datetime(2026, 10, 21, 4, 0, tzinfo=timezone.utc)
        second = process_once(self.root, config=self._config(), **kwargs)
        self.assertNotEqual(second.get("status"), "error", second)
        self.assertEqual(len(self._runs()), 2)


class ConditionCapTests(ConditionRetryFixture):
    def test_cap_escalates_without_further_relaunch(self) -> None:
        monitor = _monitor("quota exceeded")
        kwargs = dict(popen=self._popen, launch_plan_builder=self._plan, monitor=monitor)
        first = process_once(self.root, config=self._config(), **kwargs)
        self.assertEqual(first["process_state"], "blocked_quota")
        state = self._runs()[0]
        state.attempts = 4
        state.next_eligible_at = "2026-10-20T00:00:00Z"
        save_run_state(self.root, state)

        self.clock.advance(hours=1)
        report = process_once(self.root, config=self._config(), **kwargs)
        self.assertEqual(report["status"], "condition_escalated", report)
        self.assertEqual(len(self._runs()), 1)
        escalated = load_run_state(self.root, state.run_id)
        assert escalated is not None
        self.assertEqual(escalated.process_state, "blocked_external")
        self.assertTrue(escalated.escalated_at)
        self.assertEqual(escalated.blocked_on, "quota:grok")
        self.assertFalse(escalated.retry_eligible)
        alert = json.loads(
            (self.root / "runtime/dispatch/builder_condition_alerts.json").read_text(encoding="utf-8")
        )
        self.assertTrue(alert["condition_escalation_active"])
        self.assertEqual(alert["escalations"][0]["run_id"], state.run_id)
        self.assertEqual(self._poke_events(), ["assignment_blocked_external"])

        again = process_once(self.root, config=self._config(), **kwargs)
        self.assertEqual(again["status"], "idle")
        self.assertEqual(len(self._runs()), 1)
        self.assertEqual(self._poke_events(), ["assignment_blocked_external"])


class RecoveryTests(ConditionRetryFixture):
    def test_recovery_seconds_from_blocked_since_to_first_activity(self) -> None:
        def monitor(process, **kwargs):
            del process
            state = kwargs["state"]
            if state.condition_retry_from_run_id:
                state.activity_events = 1
                return SimpleNamespace(
                    exit_code=0, timed_out=False,
                    stdout='{"type":"text","data":"resumed"}\n{"type":"end","stopReason":"end_turn"}', stderr="",
                    orphaned=False, deadline_state=None,
                )
            return SimpleNamespace(
                exit_code=1, timed_out=False, stdout="", stderr="quota exceeded",
                orphaned=False, deadline_state=None,
            )

        kwargs = dict(popen=self._popen, launch_plan_builder=self._plan, monitor=monitor)
        first = process_once(self.root, config=self._config(), **kwargs)
        self.assertEqual(first["process_state"], "blocked_quota")
        original = self._runs()[0]

        self.clock.advance(minutes=15)
        second = process_once(self.root, config=self._config(), **kwargs)
        self.assertEqual(second["process_state"], "completed", second)
        runs = self._runs()
        self.assertEqual(len(runs), 2)
        latest = runs[0]
        self.assertEqual(latest.recovered_at, "2026-10-21T00:15:00Z")
        self.assertEqual(latest.recovery_seconds, 900)
        self.assertEqual(latest.blocked_since, original.blocked_since)
        reloaded_original = load_run_state(self.root, original.run_id)
        assert reloaded_original is not None
        self.assertFalse(reloaded_original.recovered_at)
        self.assertCountEqual(
            self._poke_events(),
            ["assignment_blocked_external", "assignment_completed"],
        )


class SupersedeWhileBlockedTests(ConditionRetryFixture):
    def test_orchestrator_supersede_still_replaces_the_lock(self) -> None:
        monitor = _monitor("quota exceeded")
        first = process_once(
            self.root,
            config=self._config(),
            popen=self._popen,
            launch_plan_builder=self._plan,
            monitor=monitor,
        )
        self.assertEqual(first["process_state"], "blocked_quota")
        blocked = self._runs()[0]
        replacement = work_lock.supersede(
            self.root,
            self.task_id,
            actor="orchestrator",
            reason="manual supersede while the builder is blocked on quota",
            holder_agent="codex",
            route="supervisor",
            assignment_id=self.assignment_id,
            run_id="manual-new",
            expected_assignment_id=self.assignment_id,
            expected_run_id=blocked.run_id,
        )
        self.assertEqual(replacement["run_id"], "manual-new")
        self.assertEqual(replacement["holder_agent"], "codex")


class ConditionRetryUnitTests(unittest.TestCase):
    def test_backoff_starts_at_15_minutes_and_caps_at_6_hours(self) -> None:
        self.assertEqual(backoff_seconds(0), 900)
        self.assertEqual(backoff_seconds(1), 1800)
        self.assertEqual(backoff_seconds(10), 6 * 3600)
        now = datetime(2026, 10, 21, tzinfo=timezone.utc)
        consumed = schedule_next_eligible(now, 1, "2026-10-21T00:00:00Z")
        self.assertEqual(consumed, now + timedelta(seconds=1800))

    def test_grok_probe_never_spawns_and_codex_auth_uses_login_status(self) -> None:
        with patch("orchestrator.process_ownership.owned_run") as spawned:
            self.assertFalse(default_builder_probe("quota:grok"))
            self.assertFalse(default_builder_probe("auth:grok"))
            spawned.assert_not_called()

        calls: list[tuple[list[str], dict]] = []

        def runner(argv, **kwargs):
            calls.append((list(argv), kwargs))
            return SimpleNamespace(returncode=0)

        with patch("orchestrator.builder_condition.resolve_executable", return_value="C:/tools/codex.exe"):
            self.assertTrue(default_builder_probe("auth:codex", runner=runner))
            self.assertFalse(default_builder_probe("quota:codex", runner=runner))
        self.assertEqual(len(calls), 1)
        argv, kwargs = calls[0]
        self.assertEqual(argv, ["C:/tools/codex.exe", "login", "status"])
        self.assertIs(kwargs["shell"], False)

    def test_claude_probe_delegates_to_m1_02(self) -> None:
        with patch(
            "orchestrator.claude_event_consumer.default_condition_probe",
            return_value=True,
        ) as delegated:
            self.assertTrue(default_builder_probe("auth:claude"))
            delegated.assert_called_once_with("auth:claude")

    def test_402_and_usage_balance_classify_as_quota(self) -> None:
        payment = classify_process_output(
            agent="composer", adapter="composer-restricted", exit_code=1, stderr="HTTP 402",
        )
        balance = classify_process_output(
            agent="composer",
            adapter="composer-restricted",
            exit_code=1,
            stderr="Grok Build usage balance exhausted",
        )
        self.assertEqual(payment.process_state, "blocked_quota")
        self.assertEqual(balance.process_state, "blocked_quota")


if __name__ == "__main__":
    unittest.main()
