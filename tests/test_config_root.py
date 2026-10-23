"""Offline regressions for pinned code/config with independent mutable state."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

from root_paths import resolve_config_root, resolve_state_root, root_metadata
from dispatch.agent_environment import build_minimal_environment
from dispatch.codex_adapter import load_codex_restricted_adapter, build_codex_command
from dispatch.execution_policy import load_execution_policy
from dispatch.agent_wake import _queue_signal
from orchestrator.quota_probe import load_config, ledger_path
from orchestrator.run_deadlines import adapter_deadlines
from orchestrator.loaders import safe_task_path, load_registry_list
from orchestrator.layer_supervisor import LayerSupervisor
from orchestrator.claude_event_consumer import ClaudeEventConsumer, watcher_status_path
from orchestrator.rotating_log import RotatingLogWriter
from orchestrator.supervisor import process_once

CODE = Path(__file__).resolve().parents[1]


class ConfigRootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "state"
        (self.state / "runtime").mkdir(parents=True)
        self.env = patch.dict(os.environ, {"AGENTIC_OS_CONFIG_ROOT": str(CODE),
                                          "AGENTIC_OS_STATE_ROOT": str(self.state)}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_old_state_configuration_cannot_weaken_launch(self):
        agents = self.state / "agents"
        agents.mkdir()
        (agents / "codex_restricted_adapter.yaml").write_text("id: old-template\n")
        self.assertFalse((agents / "quota_probe.yaml").exists())
        self.assertFalse((agents / "run_deadlines.yaml").exists())
        worktree = self.state / "worktree"
        worktree.mkdir()
        plan = build_codex_command(load_codex_restricted_adapter(self.state),
            repo_root=self.state, worktree_path=str(worktree), run_id="offline",
            stdout_path=str(self.state / "logs/out"), stderr_path=str(self.state / "logs/err"),
            agent_output_path=str(worktree / "output.md"), timeout_seconds=1800)
        self.assertTrue(Path(plan.context_bundle_dir).is_relative_to(self.state))
        self.assertIn("--ignore-user-config", plan.argv)
        self.assertIn("mcp_servers={}", plan.argv)
        self.assertTrue(load_config(self.state)["enabled"])
        self.assertEqual(load_codex_restricted_adapter(self.state), load_codex_restricted_adapter(CODE))
        self.assertEqual(load_execution_policy(self.state), yaml.safe_load(
            (CODE / "config/execution-policy.yaml").read_text(encoding="utf-8")))
        self.assertTrue(load_execution_policy(self.state)["work_lock_enabled"])
        # A distinguishing value proves this is a file read, rather than default limits.
        config = Path(self.tmp.name) / "config"
        (config / "agents").mkdir(parents=True)
        (config / "config").mkdir()
        (config / "agents/run_deadlines.yaml").write_text(
            "codex-restricted: {startup_seconds: 17, inactivity_seconds: 29}\n")
        with patch.dict(os.environ, {"AGENTIC_OS_CONFIG_ROOT": str(config)}):
            policy = adapter_deadlines(self.state, "codex-restricted", 101)
        self.assertEqual((policy.startup_seconds, policy.inactivity_seconds, policy.overall_seconds),
                         (17, 29, 101))

    def test_root_validation_and_library_defaults(self):
        self.assertEqual(resolve_state_root(CODE), self.state.resolve())
        self.assertEqual(resolve_config_root(self.state), CODE)
        with self.assertRaisesRegex(ValueError, "requires agents/ and config/"):
            resolve_config_root(CODE, self.state)
        with self.assertRaisesRegex(ValueError, "requires runtime/"):
            resolve_state_root(CODE, Path(self.tmp.name) / "absent")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_config_root(self.state), self.state.resolve())

    def test_mutable_paths_and_task_lookup_remain_in_state(self):
        task = self.state / "tasks/active/T.yaml"
        task.parent.mkdir(parents=True)
        task.write_text("id: T\n")
        self.assertEqual(safe_task_path(self.state, "tasks/active/T.yaml"), task)
        signal = _queue_signal(self.state, "composer", {"assignment_id": "offline"})
        self.assertTrue((self.state / signal).exists())
        self.assertTrue(ledger_path(self.state).is_relative_to(self.state))
        log = self.state / "logs/test.jsonl"
        RotatingLogWriter(log).log_json({"offline": True})
        self.assertTrue(log.is_file())
        from dispatch import work_lock
        from dispatch.worktree_allocator import run_git, resolve_worktree_root
        from orchestrator.runtime_store import RunState, save_run_state
        work_lock.acquire(self.state, "T", holder_agent="codex", route="offline", run_id="offline")
        self.assertTrue(work_lock.lock_path(self.state, "T").is_file())
        state = RunState(run_id="offline", assignment_id="offline", task_id="T",
                         assigned_agent="codex", adapter="codex-restricted")
        self.assertTrue(save_run_state(self.state, state).is_relative_to(self.state))
        with patch("orchestrator.process_ownership.owned_run") as git:
            run_git(self.state, ["rev-parse", "HEAD"])
        self.assertEqual(git.call_args.kwargs["cwd"], self.state)
        self.assertEqual(resolve_worktree_root(self.state),
                         self.state.parent / (self.state.name + "-worktrees"))

        from dashboard.app import load_roles_registry, load_skills_registry, load_mcps_registry, load_teams_registry
        for loader in (load_roles_registry, load_skills_registry, load_mcps_registry, load_teams_registry):
            self.assertEqual(loader(self.state), loader(CODE))
        self.assertEqual(load_registry_list(self.state, "teams/registry.yaml", "teams"),
                         load_registry_list(CODE, "teams/registry.yaml", "teams"))

    def test_child_commands_and_environment_use_both_roots(self):
        from scripts import run_supervisor_layers
        parent = Mock()
        parent.run.return_value = 0
        with patch.object(run_supervisor_layers, "LayerSupervisor", return_value=parent) as cls, \
             patch("sys.argv", ["run_supervisor_layers", "--state-root", str(self.state),
                                "--config-root", str(CODE)]):
            self.assertEqual(run_supervisor_layers.main(), 0)
        root, commands = cls.call_args.args
        self.assertEqual(root, self.state)
        for command in commands.values():
            self.assertEqual(command[command.index("--state-root") + 1], str(self.state))
            self.assertEqual(command[command.index("--config-root") + 1], str(CODE))
        process = Mock(pid=123, stderr=None)
        popen = Mock(return_value=process)
        supervisor = LayerSupervisor(self.state, commands, popen=popen)
        supervisor.start(supervisor.children["builder"], 0)
        env = popen.call_args.kwargs["env"]
        for key, value in {"AGENTIC_OS_STATE_ROOT": str(self.state),
                           "AGENTIC_OS_CONFIG_ROOT": str(CODE)}.items():
            self.assertEqual(env[key], value)
            self.assertEqual(build_minimal_environment(env)[0][key], value)

    def test_layer_entrypoints_default_to_code_checkout_and_export_roots(self):
        from scripts import run_orchestrator, run_claude_event_consumer
        with patch.dict(os.environ, {}, clear=True):
            argv = ["entrypoint", "--state-root", str(self.state), "--once"]
            with patch("sys.argv", argv), patch.object(run_orchestrator, "process_once",
                    return_value={"status": "idle"}) as process:
                self.assertEqual(run_orchestrator.main(), 0)
            self.assertEqual(process.call_args.args[0], self.state)
            self.assertEqual(os.environ["AGENTIC_OS_CONFIG_ROOT"], str(CODE))
            consumer = Mock()
            consumer.process_once.return_value = {"status": "idle"}
            with patch("sys.argv", argv), patch.object(run_claude_event_consumer,
                    "ClaudeEventConsumer", return_value=consumer) as cls:
                self.assertEqual(run_claude_event_consumer.main(), 0)
            self.assertEqual(cls.call_args.args[0], self.state)
            self.assertEqual(os.environ["AGENTIC_OS_STATE_ROOT"], str(self.state))

    def test_continuous_builder_status_retains_startup_audit(self):
        from orchestrator import supervisor
        def stop(_):
            supervisor.STOP_REQUESTED = True
        with patch.object(supervisor.signal, "signal"), \
             patch.object(supervisor, "process_once", return_value={"status": "idle"}), \
             patch.object(supervisor.time, "sleep", side_effect=stop):
            supervisor.run_forever(self.state)
        status = json.loads((self.state / "runtime/dispatch/supervisor_status.json").read_text())
        for key, value in root_metadata(self.state).items():
            self.assertEqual(status[key], value)

    def test_all_layer_statuses_record_config_sha_and_state_root(self):
        expected = root_metadata(self.state)
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=CODE,
                              capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(expected["config_root_git_sha"], head)
        supervisor = LayerSupervisor(self.state, {})
        supervisor.save()
        consumer = ClaudeEventConsumer(self.state)
        consumer.process_once()
        process_once(self.state)
        for path in (supervisor.path, watcher_status_path(self.state),
                     self.state / "runtime/dispatch/supervisor_status.json"):
            status = json.loads(path.read_text())
            for key, value in expected.items():
                self.assertEqual(status[key], value)


if __name__ == "__main__":
    unittest.main()
