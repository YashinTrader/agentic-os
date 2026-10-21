"""Paid recovery probes: fake CLIs and deterministic clocks only."""
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import yaml

from orchestrator import quota_probe as qp
from orchestrator.builder_condition import reevaluate_blocked_builders


class QuotaProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "agents").mkdir()
        self.configure()
        self.now = datetime(2026, 10, 21, tzinfo=timezone.utc)
        monotonic = patch.object(qp.time, "monotonic", return_value=100.0)
        self.monotonic = monotonic.start()
        self.addCleanup(monotonic.stop)

    def configure(self, **values):
        config = dict(enabled=True, min_interval_seconds=3600, codex_model="cheap-test")
        config.update(values)
        (self.root / "agents/quota_probe.yaml").write_text(yaml.safe_dump(config))

    def state(self, run_id="one", provider="codex", **values):
        data = dict(run_id=run_id, blocked_on=f"quota:{provider}", attempts=0,
                    condition_retry_dispatched_at=None, escalated_at=None,
                    next_eligible_at="2026-10-22T00:00:00Z", blocked_since="2026-10-21T00:00:00Z")
        data.update(values)
        return SimpleNamespace(**data)

    def test_no_blocked_runs_or_auth_only_never_spawns(self):
        with patch.object(qp, "run_quota_probe") as run:
            self.assertEqual(qp.probe_blocked_providers(self.root, [], now=self.now), set())
            qp.probe_blocked_providers(self.root, [self.state(blocked_on="auth:codex")], now=self.now)
        run.assert_not_called()

    def test_hourly_reservation_survives_new_call_and_failure(self):
        with patch.object(qp, "run_quota_probe", return_value={"outcome": "failure", "exit_code": 1,
                                                               "classification": "blocked_quota"}) as run:
            for seconds in (0, 3599, 3600):
                qp.probe_blocked_providers(Path(str(self.root)), [self.state()],
                                           now=self.now + timedelta(seconds=seconds))
            self.assertEqual(run.call_count, 2)
        status = qp.paid_probe_status(self.root, now=self.now + timedelta(hours=1))
        self.assertEqual(status["codex"]["paid_probes_24h"], 2)
        self.assertEqual(status["codex"]["last_paid_probe_at"], "2026-10-21T01:00:00Z")

    def test_new_python_process_obeys_persisted_reservation(self):
        with patch.object(qp, "run_quota_probe", return_value={"outcome": "failure", "exit_code": 1,
                                                               "classification": "blocked_quota"}):
            qp.probe_blocked_providers(self.root, [self.state()], now=self.now)
        code = """
import sys
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from orchestrator import quota_probe as qp
state = SimpleNamespace(blocked_on='quota:codex', condition_retry_dispatched_at=None, escalated_at=None)
with patch.object(qp, 'run_quota_probe') as run:
    qp.probe_blocked_providers(Path(sys.argv[1]), [state], now=datetime(2026,10,21,tzinfo=timezone.utc))
    assert run.call_count == 0, 'persisted interval was ignored'
"""
        completed = subprocess.run([sys.executable, "-c", code, str(self.root)],
                                   capture_output=True, text=True, timeout=15, shell=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_contending_supervisor_cannot_probe(self):
        with qp._guard(qp.ledger_path(self.root)), patch.object(qp, "run_quota_probe") as run:
            self.assertEqual(qp.probe_blocked_providers(self.root, [self.state()], now=self.now), set())
        run.assert_not_called()

    def test_sequential_provider_delay_is_included_in_reservation(self):
        # batch start; codex reservation/start/end; grok reservation/start/end
        self.monotonic.side_effect = [0, 0, 0, 120, 120, 120, 120]
        with patch.object(qp, "run_quota_probe", return_value={"outcome": "failure", "exit_code": 1,
                                                               "classification": "blocked_quota"}):
            qp.probe_blocked_providers(self.root, [self.state(), self.state(provider="grok")], now=self.now)
        ledger = json.loads(qp.ledger_path(self.root).read_text())
        self.assertEqual(ledger["grok"]["last_paid_probe_at"], "2026-10-21T00:02:00Z")

    def test_success_persists_eligibility_for_all_runs_before_single_dispatch(self):
        states = [self.state("one"), self.state("two")]
        with patch("orchestrator.builder_condition.latest_condition_runs", return_value=states), \
             patch("orchestrator.builder_condition.save_run_state") as save, \
             patch("orchestrator.builder_condition.dispatch_condition_retry", return_value={"status": "launched"}) as dispatch, \
             patch.object(qp, "run_quota_probe", return_value={"outcome": "success", "exit_code": 0,
                                                               "classification": "completed"}) as run:
            reevaluate_blocked_builders(self.root, config=SimpleNamespace(now=lambda: self.now), launch=Mock())
        self.assertEqual(run.call_count, 1)
        self.assertEqual(save.call_count, 2)
        self.assertEqual(dispatch.call_count, 1)
        self.assertTrue(all(s.next_eligible_at == "2026-10-21T00:00:00Z" for s in states))

    def test_interval_validation_and_explicit_override(self):
        self.configure(min_interval_seconds=3599)
        with self.assertRaises(ValueError):
            qp.load_config(self.root)
        self.configure(min_interval_seconds=60, owner_override=True)
        self.assertEqual(qp.load_config(self.root)["min_interval_seconds"], 60)

    def test_disabled_missing_config_and_corrupt_ledger_fail_closed(self):
        with patch.object(qp, "run_quota_probe") as run:
            self.configure(enabled=False)
            qp.probe_blocked_providers(self.root, [self.state()], now=self.now)
            (self.root / "agents/quota_probe.yaml").unlink()
            qp.probe_blocked_providers(self.root, [self.state()], now=self.now)
            self.configure()
            path = qp.ledger_path(self.root)
            path.parent.mkdir(parents=True)
            for value in ('broken', '[]', '{"codex": {"last_paid_probe_at":"broken"}}'):
                path.write_text(value)
                qp.probe_blocked_providers(self.root, [self.state()], now=self.now)
        run.assert_not_called()

    def test_provider_windows_are_independent_and_evidence_is_append_only(self):
        with patch.object(qp, "run_quota_probe", return_value={"outcome": "failure", "exit_code": 1,
                                                               "classification": "blocked_quota"}):
            qp.probe_blocked_providers(self.root, [self.state()], now=self.now)
            original = qp.evidence_path(self.root).read_bytes()
            qp.probe_blocked_providers(self.root, [self.state(provider="grok")], now=self.now)
        self.assertTrue(qp.evidence_path(self.root).read_bytes().startswith(original))
        rows = [json.loads(line) for line in qp.evidence_path(self.root).read_text().splitlines()]
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[-1]["classification"], "blocked_quota")
        self.assertTrue({"provider", "started_at", "duration", "outcome", "exit_code", "classification"} <= rows[-1].keys())
        status = qp.paid_probe_status(self.root, now=self.now + timedelta(hours=24))
        self.assertEqual(status["codex"]["paid_probes_24h"], 0)

    def test_failure_stays_blocked_and_exhausted_runs_never_probe(self):
        state = self.state()
        config = SimpleNamespace(now=lambda: self.now)
        with patch("orchestrator.builder_condition.latest_condition_runs", return_value=[state]), \
             patch("orchestrator.builder_condition.consider_probe", return_value=False), \
             patch("orchestrator.builder_condition.dispatch_condition_retry") as dispatch, \
             patch.object(qp, "run_quota_probe", return_value={"outcome": "failure", "exit_code": 1,
                                                               "classification": "blocked_quota"}) as run:
            self.assertIsNone(reevaluate_blocked_builders(self.root, config=config, launch=Mock()))
            self.assertIsNone(reevaluate_blocked_builders(self.root, config=config, launch=Mock()))
        self.assertEqual(run.call_count, 1)
        dispatch.assert_not_called()
        self.assertEqual(state.next_eligible_at, "2026-10-22T00:00:00Z")
        state.attempts = 4
        with patch("orchestrator.builder_condition.latest_condition_runs", return_value=[state]), \
             patch("orchestrator.builder_condition.escalate_condition_block"), \
             patch("orchestrator.builder_condition.save_run_state"), \
             patch.object(qp, "run_quota_probe") as run:
            reevaluate_blocked_builders(self.root, config=config, launch=Mock())
        run.assert_not_called()

    def test_probe_crash_reserves_interval_and_records_failure(self):
        with patch.object(qp, "run_quota_probe", side_effect=RuntimeError("fake")) as run:
            qp.probe_blocked_providers(self.root, [self.state()], now=self.now)
            qp.probe_blocked_providers(self.root, [self.state()], now=self.now)
        run.assert_called_once()
        final = json.loads(qp.evidence_path(self.root).read_text().splitlines()[-1])
        self.assertEqual(final["classification"], "probe_error")

    def fake_probe(self, provider, stdout, stderr="", code=0, hung=False):
        proc = Mock(returncode=code)
        proc.communicate.side_effect = subprocess.TimeoutExpired("fake", 120) if hung else None
        proc.communicate.return_value = (stdout, stderr)
        with patch.object(qp, "resolve_executable", return_value="fake-cli"), \
             patch.object(qp, "owned_popen", return_value=proc) as spawn, \
             patch.object(qp, "terminate_owned") as kill:
            result = qp.run_quota_probe(provider, config=qp.load_config(self.root))
        return result, spawn.call_args, kill

    def test_codex_argv_isolated_and_success_is_structured(self):
        result, call, _ = self.fake_probe("codex", '{"type":"turn.completed"}\n')
        self.assertEqual(result["outcome"], "success")
        argv = call.args[0]
        for required in ("mcp_servers={}", "model_reasoning_effort=low", "read-only", "cheap-test", "--skip-git-repo-check"):
            self.assertIn(required, argv)
        self.assertFalse(any("bypass" in arg or "always-approve" in arg for arg in argv))
        self.assertIs(call.kwargs["shell"], False)
        self.assertEqual(call.kwargs["stdin"], subprocess.DEVNULL)
        self.assertFalse(Path(call.kwargs["cwd"]).exists())
        result, _, _ = self.fake_probe("codex", 'ok')
        self.assertEqual(result["outcome"], "failure")

    def test_failure_overrides_completion(self):
        for text in ('{"type":"turn.completed"}\n{"type":"turn.failed"}',
                     '{"type":"turn.completed"}\nusage limit reached'):
            result, _, _ = self.fake_probe("codex", text)
            self.assertEqual(result["outcome"], "failure")
        for provider, text in (("grok", '{"result":"402 balance exhausted"}'),
                               ("grok", '{"is_error":true,"result":"bad"}'),
                               ("claude", 'usage limit reached')):
            result, _, _ = self.fake_probe(provider, text)
            self.assertEqual(result["outcome"], "failure")

    def test_other_provider_commands_and_results(self):
        for provider, output in (("grok", '{"result":"ok","is_error":false}'), ("claude", "ok")):
            result, call, _ = self.fake_probe(provider, output)
            self.assertEqual(result["outcome"], "success")
            self.assertIn("Reply with exactly: ok", call.args[0])
            self.assertIn("--single" if provider == "grok" else "haiku", call.args[0])

    def test_hung_probe_terminates_owned_tree(self):
        result, _, kill = self.fake_probe("codex", "", hung=True)
        self.assertEqual(result["classification"], "timed_out")
        kill.assert_called_once()

    def test_missing_executable_and_launch_error(self):
        with patch.object(qp, "resolve_executable", return_value=None):
            self.assertEqual(qp.run_quota_probe("codex", config={})["classification"], "executable_missing")
        with patch.object(qp, "resolve_executable", return_value="fake"), \
             patch.object(qp, "owned_popen", side_effect=OSError("fake")):
            self.assertEqual(qp.run_quota_probe("claude", config={})["classification"], "launch_error")

    def test_repository_default_model(self):
        self.assertEqual(qp.load_config(Path(__file__).resolve().parents[1])["codex_model"], "gpt-6.1-sol")

    def test_misconfigured_probe_is_distinct_and_throttled(self):
        for output in (
            'The model is not supported when using Codex with a ChatGPT account.\nturn.failed',
            'invalid_request_error', 'unknown model', 'auth-plan mismatch',
            'unsupported model; quota unavailable',
        ):
            with self.subTest(output=output):
                result = qp._classify("codex", output, "", 1)
                self.assertEqual(result["classification"], "probe_misconfigured")
        with patch.object(qp, "run_quota_probe", return_value=result) as run:
            for seconds in (0, 3599):
                self.assertEqual(qp.probe_blocked_providers(
                    self.root, [self.state()], now=self.now + timedelta(seconds=seconds)), set())
            run.assert_called_once()
            status = qp.paid_probe_status(self.root, now=self.now)
            self.assertIn("alert_reason", status["codex"])
            evidence = json.loads(qp.evidence_path(self.root).read_text().splitlines()[-1])
            self.assertEqual(evidence["classification"], "probe_misconfigured")
            self.assertIn("reason", evidence)
            qp.probe_blocked_providers(self.root, [self.state()], now=self.now + timedelta(seconds=3600))
            self.assertEqual(run.call_count, 2)
        quota = qp._classify("codex", "usage limit reached", "", 1)
        self.assertEqual(quota["classification"], "blocked_quota")
        with patch.object(qp, "run_quota_probe", return_value=quota):
            qp.probe_blocked_providers(self.root, [self.state()], now=self.now + timedelta(seconds=7200))
        self.assertNotIn("alert_reason", qp.paid_probe_status(self.root, now=self.now)["codex"])

    def test_supervisor_status_contains_paid_probe_fields(self):
        from orchestrator import supervisor
        result = qp._classify("codex", "unknown model", "", 1)
        with patch.object(qp, "run_quota_probe", return_value=result):
            qp.probe_blocked_providers(self.root, [self.state()], now=self.now)
        def stop(*args, **kwargs):
            supervisor.STOP_REQUESTED = True
            return {"status": "idle"}
        with patch.object(supervisor, "process_once", side_effect=stop), \
             patch.object(supervisor.signal, "signal"), \
             patch.object(supervisor.layer_heartbeat, "tick"), \
             patch.object(supervisor.time, "sleep"):
            supervisor.run_forever(self.root, config=supervisor.SupervisorConfig(now=lambda: self.now))
        status = json.loads((self.root / "runtime/dispatch/supervisor_status.json").read_text())
        self.assertEqual(status["quota_probes"]["codex"]["paid_probes_24h"], 1)
        self.assertEqual(status["quota_probe_alerts"]["codex"]["classification"], "probe_misconfigured")
        self.assertTrue(status["quota_probe_alerts"]["codex"]["reason"])


if __name__ == "__main__":
    unittest.main()
