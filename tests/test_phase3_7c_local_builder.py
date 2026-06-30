"""Phase 3.7C — autonomous local builder tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_local_builder import (  # noqa: E402
    RESULT_BLOCKED,
    RESULT_COMPLETED_UNVERIFIED,
    RESULT_COMPLETED_VERIFIED,
    _git_changed_files,
    _parse_porcelain_changed_path,
    run_local_builder,
)
from dispatch.codex_local_builder_gate import task_execution_mode  # noqa: E402
from dispatch.codex_local_builder_gate import evaluate_local_builder_gates  # noqa: E402
from dispatch.execution_policy import load_execution_policy, validate_execution_policy  # noqa: E402
from dispatch.execution_route_policy import (  # noqa: E402
    DEDICATED_CANARY_RUNNER_REASON,
    ROUTE_CODEX_LOCAL_BUILDER,
    ROUTE_GENERIC_DISPATCH,
    evaluate_execution_route,
)
from dispatch.codex_adapter import load_codex_restricted_adapter  # noqa: E402
from dispatch.execution_gate import evaluate_execution_gates  # noqa: E402
from dispatch.agent_environment import codex_authentication_available, environment_preview  # noqa: E402
from dispatch.local_builder_runs import list_run_summaries  # noqa: E402


def _copy_repo_ignore(dirpath: str, names: list[str]) -> set[str]:
    ignored = set(shutil.ignore_patterns(".git", "__pycache__", "*.pyc")(dirpath, names))
    if Path(dirpath).name == "active":
        ignored.add("T-FIRST-AUTONOMOUS-CODEX-BUILD.yaml")
    return ignored


class LocalBuilderFixtureMixin:
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name) / "repo"
        shutil.copytree(
            REPO_ROOT,
            self.root,
            ignore=_copy_repo_ignore,
        )
        self._init_git()
        self._write_auto_task()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _init_git(self) -> None:
        for cmd in (
            ["git", "init"],
            ["git", "config", "user.email", "builder@test.local"],
            ["git", "config", "user.name", "Builder Test"],
            ["git", "add", "-A"],
            ["git", "commit", "-m", "init"],
        ):
            subprocess.run(cmd, cwd=self.root, capture_output=True, text=True, check=False)

    def _write_auto_task(self) -> None:
        task = {
            "id": "T-LBUILDER-TEST",
            "title": "Local builder test task",
            "status": "ready",
            "owner": "codex",
            "reviewer": "claude",
            "created_by": "composer",
            "created_at": "2026-06-30T12:00:00Z",
            "updated_at": "2026-06-30T12:00:00Z",
            "phase": "3.7C",
            "priority": "low",
            "risk_level": "low",
            "requires_human_approval": False,
            "objective": "Test local builder",
            "context": "test",
            "goals": [],
            "non_goals": [],
            "inputs": [],
            "outputs": [],
            "constraints": [],
            "acceptance": [],
            "execution": {
                "mode": "auto_local_worktree",
                "adapter": "codex-restricted",
                "timeout_seconds": 120,
                "allowed_paths": ["docs/**", "handoffs/**"],
                "forbidden_operations": [
                    "git_push",
                    "git_merge",
                    "deploy",
                    "production_access",
                    "mcp_execution",
                    "mcp_invoke",
                    "browser_automation",
                    "email_side_effects",
                ],
            },
            "verification": {
                "commands": [f'{sys.executable} -c "print(1)"'],
                "run_full_tests": False,
            },
        }
        path = self.root / "tasks" / "active" / "T-LBUILDER-TEST.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(task, sort_keys=False), encoding="utf-8")
        self.task_path = path


class ExecutionPolicyTests(unittest.TestCase):
    def test_policy_parses(self) -> None:
        policy = load_execution_policy(REPO_ROOT)
        self.assertEqual(policy["mode"], "auto_local_worktree")
        self.assertIn("codex-restricted", policy["enabled_adapters"])
        self.assertEqual(validate_execution_policy(policy), [])


class RoutePolicyTests(unittest.TestCase):
    def test_generic_blocks_codex(self) -> None:
        adapter = load_codex_restricted_adapter(REPO_ROOT)
        decision = evaluate_execution_route(adapter, ROUTE_GENERIC_DISPATCH)
        self.assertFalse(decision.allowed)
        self.assertIn(DEDICATED_CANARY_RUNNER_REASON, decision.reasons)

    def test_local_builder_allowed(self) -> None:
        adapter = load_codex_restricted_adapter(REPO_ROOT)
        decision = evaluate_execution_route(adapter, ROUTE_CODEX_LOCAL_BUILDER)
        self.assertTrue(decision.allowed)

    def test_no_human_approval_on_adapter(self) -> None:
        adapter = load_codex_restricted_adapter(REPO_ROOT)
        self.assertFalse(adapter.get("phase3_7b_authorization_required"))
        self.assertIn(adapter.get("approval_level"), {"none", "standing_policy"})


class LocalBuilderGateTests(LocalBuilderFixtureMixin, unittest.TestCase):
    def test_gates_allow_without_approval(self) -> None:
        adapter = load_codex_restricted_adapter(self.root)
        task = yaml.safe_load(self.task_path.read_text(encoding="utf-8"))
        policy = load_execution_policy(self.root)
        gate = evaluate_local_builder_gates(
            self.root,
            task=task,
            adapter=adapter,
            allocation_record={
                "allocation_id": "alloc-test",
                "worktree_path": str(self.root / "wt"),
                "task_id": "T-LBUILDER-TEST",
            },
            policy=policy,
        )
        self.assertTrue(gate.allowed, gate.blocked_reasons)


class LocalBuilderRunnerTests(LocalBuilderFixtureMixin, unittest.TestCase):
    def test_runner_creates_artifacts_with_mock_codex(self) -> None:
        handoff_rel = "handoffs/T-LBUILDER-TEST__codex__to__claude.md"

        def fake_runner(argv, **kwargs):
            wt = Path(kwargs["cwd"])
            (wt / "docs").mkdir(exist_ok=True)
            (wt / "docs" / "builder-test.md").write_text("# test\n", encoding="utf-8")
            (wt / "handoffs").mkdir(exist_ok=True)
            (wt / handoff_rel).write_text("# Handoff\n", encoding="utf-8")
            mock = MagicMock()
            mock.returncode = 0
            mock.stdout = "ok"
            mock.stderr = ""
            return mock

        os.environ["OPENAI_API_KEY"] = "test-key-for-gate"
        try:
            result = run_local_builder(
                self.root,
                task_path=self.task_path,
                skip_codex=True,
                fake_codex_exit=0,
                subprocess_runner=fake_runner,
            )
        finally:
            os.environ.pop("OPENAI_API_KEY", None)

        run_dir = Path(result.run_dir)
        self.assertFalse(result.blocked_reasons, result.blocked_reasons)
        self.assertTrue((run_dir / "result.json").is_file())
        self.assertTrue((run_dir / "worktree_allocation.json").is_file())
        self.assertTrue((run_dir / "execution_policy.json").is_file())
        self.assertTrue((run_dir / "git_status_before.txt").is_file())
        self.assertIn(result.status, {RESULT_COMPLETED_VERIFIED, RESULT_COMPLETED_UNVERIFIED, RESULT_BLOCKED})

    def test_generic_executor_still_blocks_codex(self) -> None:
        adapter = load_codex_restricted_adapter(self.root)
        preview = {
            "adapter_id": "codex-restricted",
            "task_id": "T-LBUILDER-TEST",
            "run_id": "run-test",
            "command": "codex exec test",
            "working_directory": str(self.root),
            "timeout_seconds": 60,
        }
        gate = evaluate_execution_gates(
            self.root,
            preview,
            adapter=adapter,
            cli_inventory={},
            approval_record=None,
            operator_execute=True,
            dry_run=False,
        )
        self.assertFalse(gate.execution_allowed)


class WorkerTests(LocalBuilderFixtureMixin, unittest.TestCase):
    def test_worker_once_idle_without_ready_task(self) -> None:
        task = yaml.safe_load(self.task_path.read_text(encoding="utf-8"))
        task["status"] = "in_progress"
        self.task_path.write_text(yaml.safe_dump(task, sort_keys=False), encoding="utf-8")

        completed = subprocess.run(
            [sys.executable, "scripts/run_local_builder_worker.py", "--once", "--json"],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0)
        report = json.loads(completed.stdout)
        self.assertIn(report["status"], {"processed", "idle", "skipped"})


class PorcelainLineParserTests(unittest.TestCase):
    def test_parse_modified_unstaged(self) -> None:
        self.assertEqual(_parse_porcelain_changed_path(" M dashboard/app.py"), "dashboard/app.py")

    def test_parse_modified_staged(self) -> None:
        self.assertEqual(_parse_porcelain_changed_path("M  dashboard/app.py"), "dashboard/app.py")

    def test_parse_added(self) -> None:
        self.assertEqual(_parse_porcelain_changed_path("A  docs/new.md"), "docs/new.md")

    def test_parse_untracked(self) -> None:
        self.assertEqual(_parse_porcelain_changed_path("?? runtime/tmp.txt"), "runtime/tmp.txt")

    def test_parse_renamed(self) -> None:
        line = "R  dashboard/old.py -> dashboard/new.py"
        self.assertEqual(_parse_porcelain_changed_path(line), "dashboard/new.py")

    def test_parse_copied(self) -> None:
        line = "C  docs/template.md -> docs/copy.md"
        self.assertEqual(_parse_porcelain_changed_path(line), "docs/copy.md")

    def test_parse_deleted_unstaged(self) -> None:
        self.assertEqual(_parse_porcelain_changed_path(" D docs/remove.md"), "docs/remove.md")

    def test_parse_deleted_staged(self) -> None:
        self.assertEqual(_parse_porcelain_changed_path("D  docs/remove.md"), "docs/remove.md")

    def test_parse_quoted_path_with_spaces(self) -> None:
        self.assertEqual(_parse_porcelain_changed_path(' M "docs/my doc.md"'), "docs/my doc.md")

    def test_parse_windows_backslash_path(self) -> None:
        self.assertEqual(_parse_porcelain_changed_path(" M dashboard\\app.py"), "dashboard/app.py")

    def test_parse_rename_with_quoted_paths(self) -> None:
        line = 'R  "old name.txt" -> "new name.txt"'
        self.assertEqual(_parse_porcelain_changed_path(line), "new name.txt")


class GitPorcelainParsingTests(LocalBuilderFixtureMixin, unittest.TestCase):
    def _commit_all(self, message: str) -> None:
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=self.root,
            check=True,
            capture_output=True,
        )

    def test_changed_files_preserves_path_prefix_after_modified_status(self) -> None:
        test_file = self.root / "dashboard" / "app.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("# original\n", encoding="utf-8")
        subprocess.run(["git", "add", "dashboard/app.py"], cwd=self.root, check=True, capture_output=True)
        self._commit_all("add dashboard")
        test_file.write_text("# modified\n", encoding="utf-8")
        changed = _git_changed_files(self.root)
        self.assertIn("dashboard/app.py", changed)

    def test_changed_files_detects_staged_add(self) -> None:
        new_file = self.root / "docs" / "porcelain-add.md"
        new_file.parent.mkdir(parents=True, exist_ok=True)
        new_file.write_text("# added\n", encoding="utf-8")
        subprocess.run(["git", "add", "docs/porcelain-add.md"], cwd=self.root, check=True, capture_output=True)
        changed = _git_changed_files(self.root)
        self.assertIn("docs/porcelain-add.md", changed)

    def test_changed_files_detects_untracked(self) -> None:
        untracked = self.root / "docs" / "porcelain-untracked.md"
        untracked.parent.mkdir(parents=True, exist_ok=True)
        untracked.write_text("# untracked\n", encoding="utf-8")
        changed = _git_changed_files(self.root)
        self.assertIn("docs/porcelain-untracked.md", changed)

    def test_changed_files_detects_rename(self) -> None:
        src = self.root / "docs" / "before.md"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("# rename\n", encoding="utf-8")
        self._commit_all("add before")
        dest = self.root / "docs" / "after.md"
        subprocess.run(["git", "mv", "docs/before.md", "docs/after.md"], cwd=self.root, check=True, capture_output=True)
        changed = _git_changed_files(self.root)
        self.assertIn("docs/after.md", changed)

    def test_changed_files_detects_deletion(self) -> None:
        doomed = self.root / "docs" / "delete-me.md"
        doomed.parent.mkdir(parents=True, exist_ok=True)
        doomed.write_text("# delete\n", encoding="utf-8")
        self._commit_all("add doomed")
        doomed.unlink()
        changed = _git_changed_files(self.root)
        self.assertIn("docs/delete-me.md", changed)

    def test_changed_files_detects_spaced_path(self) -> None:
        spaced = self.root / "docs" / "spaced file.md"
        spaced.parent.mkdir(parents=True, exist_ok=True)
        spaced.write_text("# spaced\n", encoding="utf-8")
        changed = _git_changed_files(self.root)
        self.assertIn("docs/spaced file.md", changed)


class RunListingTests(unittest.TestCase):
    def test_list_runs_tolerates_missing(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            self.assertEqual(list_run_summaries(root), [])


class CodexAuthTests(unittest.TestCase):
    def test_chatgpt_session_auth_does_not_require_openai_api_key_env(self) -> None:
        adapter = load_codex_restricted_adapter(REPO_ROOT)
        auth_ok, _ = codex_authentication_available()
        if not auth_ok:
            self.skipTest("Codex authentication not available in this environment")
        preview = environment_preview(adapter)
        self.assertEqual(preview.get("blocked_reasons"), [])


class AdapterConfigTests(unittest.TestCase):
    def test_local_builder_adapter_config(self) -> None:
        adapter = load_codex_restricted_adapter(REPO_ROOT)
        self.assertEqual(adapter["execution_scope"], "local_worktree")
        self.assertEqual(adapter["required_execution_route"], "codex_local_builder")
        self.assertFalse(adapter["phase3_7b_authorization_required"])


class TaskModeTests(unittest.TestCase):
    def test_task_execution_mode(self) -> None:
        task = yaml.safe_load(
            (REPO_ROOT / "tasks" / "active" / "T-FIRST-AUTONOMOUS-CODEX-BUILD.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(task_execution_mode(task), "auto_local_worktree")


if __name__ == "__main__":
    unittest.main()