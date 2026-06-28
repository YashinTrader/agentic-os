from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.preview import (  # noqa: E402
    build_dispatch_preview,
    command_tokens,
    load_adapter_registry,
    persist_preview,
    validate_command_allowlist,
)


REQUIRED_PREVIEW_FIELDS = {
    "run_id",
    "mode",
    "executed",
    "dispatch_allowed",
    "command",
    "working_directory",
    "scope_paths",
    "timeout_seconds",
    "env_vars_required",
    "secrets_required",
    "expected_outputs",
    "logs_path",
    "handoff_path",
    "rollback_strategy",
    "risk_gate",
    "approval_gate",
    "statement",
}


class DispatchPreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        ignore = shutil.ignore_patterns(".codex", "__pycache__", "*.pyc", "runtime/orchestrator/runs/*")
        shutil.copytree(REPO_ROOT, self.root, ignore=ignore)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _seed_plan_task(
        self,
        *,
        task_id: str = "T-PREVIEW-001",
        agent: str = "composer",
        objective: str = "Add validator tests for protocol schema",
        risk_level: str = "low",
        requires_human: bool = False,
    ) -> None:
        task_dir = self.root / "tasks" / "active"
        task_dir.mkdir(parents=True, exist_ok=True)
        task = {
            "id": task_id,
            "title": "Preview test task",
            "owner": agent,
            "reviewer": "claude",
            "created_by": "composer",
            "status": "ready",
            "phase": "3.0",
            "created_at": "2026-06-07T24:00:00Z",
            "updated_at": "2026-06-07T24:00:00Z",
            "priority": "medium",
            "risk_level": risk_level,
            "requires_human_approval": requires_human,
            "human_approval_checklist": [],
            "objective": objective,
            "context": objective,
            "goals": [objective],
            "non_goals": [],
            "inputs": ["scripts/validate.py"],
            "outputs": ["tests/test_dispatch_preview.py"],
            "constraints": ["No execution"],
            "acceptance": ["Preview tests pass"],
            "notes": "",
        }
        (task_dir / f"{task_id}.yaml").write_text(yaml.safe_dump(task, sort_keys=False), encoding="utf-8")

        orch = self.root / "runtime" / "orchestrator"
        orch.mkdir(parents=True, exist_ok=True)
        plan = {
            "run_id": "run-preview-test",
            "task_id": task_id,
            "recommended_primary_agent": agent,
            "recommended_reviewer": "claude",
            "approval_level": "reviewer",
            "approval_required": True,
            "files_to_inspect": ["scripts/validate.py"],
            "executed_automatically": False,
        }
        state = {
            "run_id": "run-preview-test",
            "task_id": task_id,
            "plan_path": str(orch / "latest_plan.json"),
            "context_pack_path": str(orch / "runs" / "run-preview-test" / "context_pack.md"),
        }
        (orch / "latest_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
        (orch / "latest_state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")

    def test_load_adapter_registry(self) -> None:
        registry = load_adapter_registry(self.root)
        adapters = registry.get("adapters", [])
        self.assertGreaterEqual(len(adapters), 4)
        ids = {a["id"] for a in adapters if isinstance(a, dict)}
        self.assertIn("composer-cli-preview", ids)

    def test_allowlist_rejects_forbidden_arg(self) -> None:
        registry = load_adapter_registry(self.root)
        adapter = next(a for a in registry["adapters"] if a["id"] == "composer-cli-preview")
        cmd = "composer agent run --execute --task-id T-1"
        errors = validate_command_allowlist(adapter, cmd)
        self.assertTrue(any("forbidden argument token" in e for e in errors))

    def test_forbidden_args_token_level_not_substring_false_positive(self) -> None:
        registry = load_adapter_registry(self.root)
        adapter = next(a for a in registry["adapters"] if a["id"] == "composer-cli-preview")
        cmd = "composer agent run --dry-run --task-id T-not--execute-safe-path"
        errors = validate_command_allowlist(adapter, cmd)
        self.assertFalse(any("forbidden" in e.lower() for e in errors))

    def test_forbidden_args_token_level_matches_exact_token(self) -> None:
        registry = load_adapter_registry(self.root)
        adapter = next(a for a in registry["adapters"] if a["id"] == "composer-cli-preview")
        cmd = 'composer agent run --dry-run --task-id "T-1" --execute'
        errors = validate_command_allowlist(adapter, cmd)
        self.assertTrue(any("forbidden argument token" in e for e in errors))

    def test_command_tokens_handle_quoted_args(self) -> None:
        tokens, warnings = command_tokens('composer run --task-id "T-abc" --dry-run')
        self.assertIn("--dry-run", tokens)
        normalized = {t.strip('"').strip("'") for t in tokens}
        self.assertIn("T-abc", normalized)
        self.assertEqual(warnings, [])

    def test_allowlist_rejects_disallowed_command_root(self) -> None:
        registry = load_adapter_registry(self.root)
        adapter = next(a for a in registry["adapters"] if a["id"] == "composer-cli-preview")
        errors = validate_command_allowlist(adapter, "rm -rf /")
        self.assertTrue(any("not in allowed_commands" in e for e in errors))

    def test_risk_gate_integration_deploy_task(self) -> None:
        self._seed_plan_task(
            objective="Dry-run plan for production deploy",
            agent="composer",
        )
        preview = build_dispatch_preview(self.root)
        self.assertEqual(preview["risk_gate"]["approval_level"], "human")
        self.assertEqual(preview["approval_gate"]["approval_level"], "human")

    def test_preview_output_shape(self) -> None:
        self._seed_plan_task()
        preview = build_dispatch_preview(self.root)
        for field in REQUIRED_PREVIEW_FIELDS:
            self.assertIn(field, preview, f"missing field {field}")
        self.assertFalse(preview["executed"])
        self.assertEqual(preview["mode"], "dry_run_preview")
        self.assertIn("composer", preview["command"])

    def test_no_subprocess_execution_in_preview_module(self) -> None:
        self._seed_plan_task()
        with patch("subprocess.run") as mock_run:
            with patch("subprocess.Popen") as mock_popen:
                preview = build_dispatch_preview(self.root)
                persist_preview(self.root, preview, write_artifacts=True)
                mock_run.assert_not_called()
                mock_popen.assert_not_called()
        self.assertFalse(preview["executed"])

    def test_preview_module_has_no_subprocess_import(self) -> None:
        import dispatch.preview as preview_mod

        source = Path(preview_mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("subprocess.run", source)
        self.assertNotIn("subprocess.Popen", source)

    def test_cli_preview_dispatch_runs(self) -> None:
        self._seed_plan_task()
        result = subprocess.run(
            [
                sys.executable,
                str(self.root / "scripts" / "preview_dispatch.py"),
                "--root",
                str(self.root),
                "--no-log",
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertIn(result.returncode, (0, 2), msg=result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data["executed"])

    def test_disabled_mcp_adapter_not_selected_by_default(self) -> None:
        self._seed_plan_task(agent="mcp", objective="Summarize logs")
        preview = build_dispatch_preview(self.root)
        self.assertFalse(preview["dispatch_allowed"])
        self.assertTrue(any("no active adapter" in e for e in preview["errors"]))
        self.assertEqual(preview["approval_gate"]["approval_level"], "blocked")
        self.assertEqual(preview["approval_gate"]["approval_status"], "blocked")
        self.assertIn("No active allowlisted adapter", preview["approval_gate"]["approval_reason"])

    def test_explicit_blocked_adapter_via_forbidden_supports_dry_run_false(self) -> None:
        self._seed_plan_task()
        preview = build_dispatch_preview(self.root, adapter_id="blocked-mcp-preview")
        self.assertFalse(preview["dispatch_allowed"])
        self.assertTrue(preview["errors"])
        self.assertEqual(preview["approval_gate"]["approval_level"], "blocked")
        self.assertEqual(preview["approval_gate"]["approval_status"], "blocked")
        self.assertIn("not active", preview["approval_gate"]["approval_reason"].lower())

    def test_log_path_has_no_double_dispatch_prefix(self) -> None:
        self._seed_plan_task()
        preview = build_dispatch_preview(self.root)
        run_id = preview["run_id"]
        self.assertTrue(run_id.startswith("dispatch-"))
        self.assertEqual(preview["logs_path"], f"logs/{run_id}.jsonl")
        self.assertNotIn("dispatch-dispatch-", preview["logs_path"])

    def test_gitignore_excludes_dispatch_artifacts(self) -> None:
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("runtime/dispatch/**", gitignore)
        self.assertIn("logs/dispatch-*.jsonl", gitignore)

    def test_adr_0013_exists_with_required_sections(self) -> None:
        path = REPO_ROOT / "decisions" / "ADR-0013-adapter-registry-schema.md"
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        for section in ("## Context", "## Decision", "## Consequences"):
            self.assertIn(section, text, f"missing {section}")
        self.assertIn("forbidden_args", text)
        self.assertIn("token-level", text.lower())

    def test_requires_human_approval_in_preview_gate(self) -> None:
        self._seed_plan_task(requires_human=True, objective="Add unit tests")
        preview = build_dispatch_preview(self.root)
        self.assertEqual(preview["approval_gate"]["approval_level"], "human")


if __name__ == "__main__":
    unittest.main()