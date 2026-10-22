"""Real redacted and synthetic glog with fake-process tests; never invoke agy or signal OS processes."""
from dataclasses import asdict
from datetime import datetime, timezone
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from dispatch import antigravity_adapter as adapter, work_lock
from orchestrator import agent_launcher
from orchestrator.run_deadlines import adapter_deadlines
from scripts.repository_verification import POST_TEST_ALLOWLIST_EXACT

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/antigravity"
MODEL = "gemini-3.8-flash"
LABEL = "Gemini 3.8 Flash (Medium)"


def parse(name="success"):
    return adapter.parse_log((FIXTURES / f"{name}.log").read_text(encoding="utf-8"),
                             requested_model=MODEL, expected_model_label=LABEL)


class EvidenceTests(unittest.TestCase):
    def test_confirmed_success_is_only_a_candidate(self):
        evidence = parse()
        self.assertTrue(evidence.model_confirmed)
        self.assertTrue(evidence.completion_signal)
        self.assertEqual(evidence.auth_state, "authenticated")
        self.assertTrue(evidence.sandbox_applied)
        self.assertEqual(evidence.mode_applied, "plan")
        self.assertEqual(adapter.classify(evidence, exit_code=0).category, "completed")
        self.assertIn("independent verification", adapter.classify(evidence, exit_code=0).detail)
        self.assertIsNone(evidence.token_usage)

    def test_failures_override_rc_zero(self):
        for fixture, category in [("silent_fallback", "model_unavailable"),
                                  ("not_logged_in", "blocked_authentication"),
                                  ("quota", "blocked_quota"), ("soft_deny", "permission_denied")]:
            with self.subTest(fixture=fixture):
                result = adapter.classify(parse(fixture), exit_code=0)
                self.assertEqual(result.category, category)
                self.assertFalse(result.retry_eligible)

    def test_deadline_precedes_success_and_other_blockers(self):
        for state in ("failed_launch", "stalled", "timed_out"):
            result = adapter.classify(parse("deadline"), exit_code=0, deadline_state=state)
            self.assertEqual(result.category, "deadline")
            self.assertEqual(result.process_state, state)

    def test_missing_and_wrong_labels_fail_closed(self):
        log = (FIXTURES / "success.log").read_text()
        for changed in (log.replace(LABEL, "Other model"),
                        "\n".join(line for line in log.splitlines() if "Propagating" not in line)):
            evidence = adapter.parse_log(changed, requested_model=MODEL, expected_model_label=LABEL)
            self.assertEqual(adapter.classify(evidence, exit_code=0).category, "model_unavailable")

    def test_pre_auth_default_can_be_resolved_later(self):
        prefix = (FIXTURES / "silent_fallback.log").read_text()
        log = prefix + (FIXTURES / "success.log").read_text()
        evidence = adapter.parse_log(log, requested_model=MODEL, expected_model_label=LABEL)
        self.assertTrue(evidence.default_resolver_seen)
        self.assertTrue(evidence.model_confirmed)
        self.assertFalse(evidence.silent_fallback_detected)
        self.assertTrue(parse("silent_fallback").silent_fallback_detected)

    def test_permission_config_warning_is_not_a_tool_denial(self):
        log = (FIXTURES / "success.log").read_text()
        log += '\nW1022 09:46:41.459003  1 permissions.go:42] Invalid "unsandboxed" permission rules found; they are ignored and grant nothing\n'
        evidence = adapter.parse_log(log, requested_model=MODEL, expected_model_label=LABEL)
        self.assertEqual(evidence.permission_config_warnings, 1)
        self.assertEqual(evidence.permission_soft_denials, 0)
        self.assertEqual(adapter.classify(evidence, exit_code=0).category, "completed")

    def test_generic_permission_text_is_not_a_tool_denial(self):
        log = (FIXTURES / "success.log").read_text()
        log += '\nI1022 09:46:41.459003  1 permissions.go:42] permission denied policy; request-review required\n'
        evidence = adapter.parse_log(log, requested_model=MODEL, expected_model_label=LABEL)
        self.assertEqual(evidence.permission_soft_denials, 0)

    def test_real_probe_is_candidate_success(self):
        evidence = parse("real_probe_success_redacted")
        result = adapter.classify(evidence, exit_code=0)
        self.assertEqual(result.category, "completed")
        self.assertIn("independent verification required", result.detail)
        self.assertEqual(evidence.conversation_id, "7ac9e791-c742-41d1-b978-89658fd0bc0e")
        self.assertTrue(evidence.model_confirmed)
        self.assertEqual(evidence.resolved_model_label, LABEL)
        self.assertTrue(evidence.sandbox_applied)
        self.assertEqual(evidence.mode_applied, "plan")
        self.assertFalse(evidence.quota_exhausted)
        self.assertIsNone(evidence.token_usage)
        self.assertEqual(evidence.permission_soft_denials, 0)
        self.assertEqual(evidence.permission_config_warnings, 1)

    def test_real_prelogin_failures_are_superseded_by_silent_auth(self):
        log = (FIXTURES / "real_probe_success_redacted.log").read_text(encoding="utf-8")
        self.assertLess(log.index("not logged into Antigravity"), log.index("silent auth succeeded"))
        self.assertEqual(parse("real_probe_success_redacted").auth_state, "authenticated")

    def test_auth_failure_after_print_attempt_overrides_success(self):
        log = (FIXTURES / "real_probe_success_redacted.log").read_text(encoding="utf-8")
        for message in ("You are not logged into Antigravity.", "Print mode: silent auth failed"):
            with self.subTest(message=message):
                evidence = adapter.parse_log(log + '\nE1022 09:47:13.459003  1 auth.go:42] ' + message,
                                             requested_model=MODEL, expected_model_label=LABEL)
                self.assertEqual(evidence.auth_state, "authentication_failed")
                self.assertEqual(adapter.classify(evidence, exit_code=0).category, "blocked_authentication")

    def test_last_model_override_wins(self):
        log = (FIXTURES / "success.log").read_text()
        log += '\nI1022 09:46:41.459003  1 model.go:42] Propagating selected model override to backend: label="Other"\n'
        self.assertFalse(adapter.parse_log(log, requested_model=MODEL, expected_model_label=LABEL).model_confirmed)

    def test_quota_refresh_is_only_liveness(self):
        evidence = parse()
        self.assertEqual(evidence.quota_events, 1)
        self.assertFalse(evidence.quota_exhausted)

    def test_completion_must_match_conversation(self):
        evidence = parse()
        evidence.completion_signal = False
        self.assertEqual(adapter.classify(evidence, exit_code=0).category, "failed")
        log = (FIXTURES / "success.log").read_text().replace(
            "Stream goroutine exited for 12345678", "Stream goroutine exited for 87654321")
        self.assertFalse(adapter.parse_log(log, requested_model=MODEL, expected_model_label=LABEL).completion_signal)
        for rc in (None, 1):
            self.assertEqual(adapter.classify(parse(), exit_code=rc).category, "failed")

    def test_missing_sandbox_or_mode_blocks_success(self):
        evidence = parse()
        evidence.sandbox_applied = False
        self.assertEqual(adapter.classify(evidence, exit_code=0).category, "permission_denied")
        self.assertEqual(adapter.classify(parse(), exit_code=0, expected_mode="accept-edits").category, "permission_denied")

    def test_evidence_does_not_copy_email_or_credentials(self):
        log = (FIXTURES / "success.log").read_text()
        log += '\nI1022 09:46:41.459003  1 auth.go:42] account=person@example.test token=synthetic-secret\n'
        evidence = adapter.parse_log(log, requested_model="person@example.test", expected_model_label=LABEL)
        serialized = json.dumps(asdict(evidence))
        self.assertNotIn("person@example.test", serialized)
        self.assertNotIn("synthetic-secret", serialized)
        self.assertIn("[redacted-email]", serialized)

    def test_unframed_text_is_not_machine_evidence(self):
        evidence = adapter.parse_log("You are not logged into Antigravity", requested_model=MODEL, expected_model_label=LABEL)
        self.assertEqual(evidence.auth_state, "unknown")
        self.assertEqual(evidence.log_events, 0)

    def test_conditions_use_existing_schedule_without_adapter_retries(self):
        now = datetime(2026, 10, 22, tzinfo=timezone.utc)
        result = adapter.condition_retry_metadata(adapter.classify(parse("quota"), exit_code=0), now=now)
        self.assertEqual(result["blocked_on"], "quota:antigravity")
        self.assertEqual(datetime.fromisoformat(result["next_eligible_at"]).timestamp() - now.timestamp(), 900)
        self.assertEqual(adapter.condition_retry_metadata(adapter.classify(parse("silent_fallback"), exit_code=0), now=now), {})


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.worktree = self.root / "isolated"
        self.worktree.mkdir()
        (self.worktree / ".git").mkdir()
        self.run_dir = self.root / "runtime/dispatch/runs/run-1"

    def plan(self, **overrides):
        args = dict(worktree=self.worktree, run_dir=self.run_dir, prompt="Analyze", model=MODEL,
                    role="read-only-analysis", deadline_seconds=300)
        args.update(overrides)
        return adapter.build_launch_plan(**args)

    def test_argv_and_static_forbidden_flag_check(self):
        plan = self.plan()
        self.assertEqual(plan.argv[1:], ["-p", "Analyze", "--model", MODEL, "--sandbox", "--print-timeout",
                         "300s", "--log-file", str(self.run_dir / "agy.log"), "--mode", "plan"])
        self.assertEqual(plan.cwd, str(self.worktree))
        self.assertFalse(plan.inherit_environment)
        self.assertNotIn("--dangerously-skip-permissions", inspect.getsource(adapter.build_launch_plan))
        self.assertNotIn("--add-dir", inspect.getsource(adapter.build_launch_plan))
        self.assertEqual(self.plan(role=adapter.DEVELOPMENT_ROLE).argv[-1], "accept-edits")

    def test_paths_roles_and_deadlines_rejected(self):
        for overrides in ({"run_dir": self.worktree / "runtime/run-1"},
                          {"run_dir": self.worktree}, {"run_dir": self.root}, {"role": "builder"},
                          {"deadline_seconds": 0}, {"deadline_seconds": 1801}, {"deadline_seconds": float("nan")},
                          {"model": "--dangerously-skip-permissions"}, {"prompt": ""}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.plan(**overrides)

    def test_secret_environment_is_not_inherited(self):
        with patch.dict("os.environ", {"GITHUB_TOKEN": "private", "OPENAI_API_KEY": "private"}):
            self.assertNotIn("GITHUB_TOKEN", self.plan().env)
            self.assertNotIn("OPENAI_API_KEY", self.plan().env)

    def test_disabled_and_absent_from_routing_defaults(self):
        config = yaml.safe_load((ROOT / "agents/antigravity_restricted_adapter.yaml").read_text())
        self.assertFalse(config["enabled"])
        self.assertFalse(config["supports_execution"])
        for directory in ("config",):
            for path in (ROOT / directory).rglob("*.yaml"):
                self.assertNotIn(adapter.ADAPTER, path.read_text(encoding="utf-8"), str(path))
        self.assertNotIn(adapter.ADAPTER, (ROOT / "agents/adapter_registry.yaml").read_text())
        with patch.object(adapter, "launch_process") as launch, self.assertRaises(PermissionError):
            adapter.execute_experiment(ROOT, task_id="T-1", run_id="r1", worktree=self.worktree,
                run_dir=self.run_dir, prompt="test", model=MODEL, expected_model_label=LABEL, role="read-only-analysis")
        launch.assert_not_called()

    def enable_fake_config(self):
        (self.root / "agents").mkdir()
        (self.root / "agents/antigravity_restricted_adapter.yaml").write_text("enabled: true\nsupports_execution: true\n")

    def execute(self, **kwargs):
        return adapter.execute_experiment(self.root, task_id="T-1", run_id="r1", worktree=self.worktree,
            run_dir=self.run_dir, prompt="test", model=MODEL, expected_model_label=LABEL, role="read-only-analysis", **kwargs)

    def test_owned_popen_path_and_lock_retained_for_review(self):
        self.enable_fake_config()
        class FakeProcess:
            pid, returncode = 123, 0
            def poll(self):
                return self.returncode
        def fake_popen(*args, **kwargs):
            self.assertFalse(kwargs["shell"])
            self.assertEqual(kwargs["cwd"], str(self.worktree))
            (self.run_dir / "agy.log").write_text((FIXTURES / "success.log").read_text())
            return FakeProcess()
        with patch("orchestrator.process_ownership.owned_popen", side_effect=fake_popen) as owned, \
             patch.object(adapter, "terminate_owned") as terminate:
            result = self.execute()
        owned.assert_called_once()
        terminate.assert_called_once()
        self.assertEqual(result["classification"]["category"], "completed")
        self.assertTrue(result["independent_verification_required"])
        self.assertEqual(work_lock.status(self.root)[0]["state"], "awaiting_review")
        with self.assertRaises(work_lock.WorkLockError):
            work_lock.acquire(self.root, "T-1", holder_agent="other", route="other", run_id="r2")
        with self.assertRaisesRegex(ValueError, "fresh"):
            self.execute()
        self.assertIn("owned_popen(", inspect.getsource(agent_launcher.launch_process))

    def test_deadline_uses_owned_termination_only(self):
        self.enable_fake_config()
        class FakeProcess:
            pid, returncode = 123, None
            def poll(self):
                return None
            def wait(self, timeout):
                self.returncode = -1
        with patch("orchestrator.process_ownership.owned_popen", return_value=FakeProcess()), \
             patch.object(adapter.RunDeadlines, "expired", return_value=("overall", "timed_out")), \
             patch.object(adapter, "terminate_owned") as terminate:
            result = self.execute()
        self.assertTrue(terminate.called)
        self.assertEqual(result["classification"]["category"], "deadline")
        self.assertEqual(work_lock.status(self.root)[0]["state"], "awaiting_review")

    def test_launch_error_preserves_work_ownership(self):
        self.enable_fake_config()
        with patch.object(adapter, "launch_process", return_value=(None, "synthetic failure")):
            result = self.execute()
        self.assertEqual(result["classification"]["category"], "failed_launch")
        self.assertEqual(work_lock.status(self.root)[0]["state"], "awaiting_review")

    def test_unexpected_monitor_error_cleans_owned_tree(self):
        self.enable_fake_config()
        class FakeProcess:
            pid = 123
            def poll(self):
                raise RuntimeError("synthetic monitor error")
        with patch("orchestrator.process_ownership.owned_popen", return_value=FakeProcess()), \
             patch.object(adapter, "terminate_owned") as terminate, \
             self.assertRaisesRegex(RuntimeError, "monitor error"):
            self.execute()
        terminate.assert_called_once()
        self.assertEqual(work_lock.status(self.root)[0]["state"], "awaiting_review")

    def test_deadline_configuration_and_handoff_allowlist(self):
        self.assertEqual(adapter_deadlines(ROOT, adapter.ADAPTER, 300).overall_seconds, 300)
        self.assertIn("handoffs/T-M2-S3-ANTIGRAVITY-CLI-ADAPTER__codex__to__claude.md", POST_TEST_ALLOWLIST_EXACT)
