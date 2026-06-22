"""Phase 3.3.1 review-fix regression tests — M2 freshness and L3 event emit observability."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.execution_gate import evaluate_execution_gates  # noqa: E402
from dispatch.executor import execute_dispatch  # noqa: E402
from dispatch.freshness import compute_preview_hash  # noqa: E402
from dispatch.preview import build_dispatch_preview, persist_preview  # noqa: E402
from dispatch.runtime_capture import append_run_event as _real_append_run_event  # noqa: E402
from scripts import validate as validate_mod  # noqa: E402


def _local_adapter() -> dict:
    return {
        "id": "local-python-exec-test",
        "status": "active",
        "supports_dry_run": True,
        "supports_execution": True,
        "adapter_type": "cli",
        "writes_files": False,
        "allowed_commands": ["python"],
        "forbidden_args": ["--execute"],
        "required_clis": ["python"],
        "command_template": "",
    }


def _base_preview(**overrides) -> dict:
    base = {
        "run_id": "dispatch-20260620T120000Z-m2test01",
        "task_id": "T-M2",
        "adapter_id": "local-python-exec-test",
        "command": 'python -c "print(\'agentic-os-executor-test\')"',
        "working_directory": "",
        "scope_paths": ["tasks/"],
        "timeout_seconds": 30,
        "secrets_required": False,
        "dispatch_allowed": True,
        "handoff_path": "handoffs/T-M2__composer__to__claude.md",
        "errors": [],
        "worktree_required": False,
        "approval_gate": {"approval_level": "none", "approval_status": "none"},
        "risk_gate": {"approval_level": "none"},
        "plan_path": "runtime/orchestrator/latest_plan.json",
    }
    base.update(overrides)
    return base


class ReviewFixFixtureMixin:
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        ignore = shutil.ignore_patterns(".codex", "__pycache__", "*.pyc", "runtime/orchestrator/runs/*")
        shutil.copytree(REPO_ROOT, self.root, ignore=ignore)
        self._seed_valid_context()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _seed_valid_context(self) -> None:
        task_dir = self.root / "tasks" / "active"
        task_dir.mkdir(parents=True, exist_ok=True)
        task = {
            "id": "T-M2",
            "title": "M2 regression",
            "owner": "composer",
            "reviewer": "claude",
            "created_by": "composer",
            "status": "ready",
            "phase": "3.3",
            "created_at": "2026-06-20T12:00:00Z",
            "updated_at": "2026-06-20T12:00:00Z",
            "priority": "low",
            "risk_level": "low",
            "requires_human_approval": False,
            "human_approval_checklist": [],
            "objective": "freshness regression",
            "context": "test",
            "goals": [],
            "non_goals": [],
            "inputs": [],
            "outputs": [],
            "constraints": [],
            "acceptance": [],
            "notes": "",
        }
        (task_dir / "T-M2.yaml").write_text(yaml.safe_dump(task, sort_keys=False), encoding="utf-8")
        orch = self.root / "runtime" / "orchestrator"
        orch.mkdir(parents=True, exist_ok=True)
        plan = {
            "run_id": "run-m2",
            "task_id": "T-M2",
            "recommended_primary_agent": "composer",
            "recommended_reviewer": "claude",
            "approval_level": "none",
            "approval_required": False,
            "files_to_inspect": [],
        }
        (orch / "latest_plan.json").write_text(json.dumps(plan), encoding="utf-8")
        state = {
            "run_id": "run-m2",
            "task_id": "T-M2",
            "task_path": "tasks/active/T-M2.yaml",
            "plan_path": "runtime/orchestrator/latest_plan.json",
            "approval_level": "none",
            "risk_level": "low",
        }
        (orch / "latest_state.json").write_text(json.dumps(state), encoding="utf-8")
        inv_dir = self.root / "runtime" / "registry"
        inv_dir.mkdir(parents=True, exist_ok=True)
        (inv_dir / "cli_inventory.yaml").write_text(
            yaml.safe_dump({"tools": [{"name": "python", "available": True, "path": sys.executable}]}, sort_keys=False),
            encoding="utf-8",
        )

    def _gate(self, preview: dict, *, execute: bool = False, dry_run: bool = False, adapter=None):
        preview = dict(preview)
        preview["working_directory"] = str(self.root)
        adapter = _local_adapter() if adapter is None else adapter
        cli_inventory = yaml.safe_load(
            (self.root / "runtime/registry/cli_inventory.yaml").read_text(encoding="utf-8")
        )
        return evaluate_execution_gates(
            self.root,
            preview,
            adapter=adapter,
            cli_inventory=cli_inventory,
            operator_execute=execute,
            dry_run=dry_run,
        )

    def _make_preview_path(self) -> Path:
        preview = build_dispatch_preview(self.root, adapter_id="local-python-exec-test")
        paths = persist_preview(self.root, preview)
        return self.root / paths["preview_path"]

    def _update_preview_plan_path(self, preview_path: Path, plan_rel: str) -> None:
        preview = json.loads(preview_path.read_text(encoding="utf-8"))
        preview["plan_path"] = plan_rel
        preview_path.write_text(json.dumps(preview, indent=2, ensure_ascii=False), encoding="utf-8")


class M2FreshnessRegressionTests(ReviewFixFixtureMixin, unittest.TestCase):
    def test_missing_live_plan_blocks_execute(self) -> None:
        (self.root / "runtime/orchestrator/latest_plan.json").unlink()
        result = self._gate(_base_preview(plan_path="runtime/orchestrator/missing_plan.json"), execute=True)
        self.assertFalse(result.execution_allowed)
        self.assertTrue(any("preview freshness cannot be verified" in r for r in result.blocked_reasons))

    def test_missing_live_plan_execute_no_subprocess(self) -> None:
        preview_path = self._make_preview_path()
        (self.root / "runtime/orchestrator/latest_plan.json").unlink()
        self._update_preview_plan_path(preview_path, "runtime/orchestrator/missing_plan.json")
        with patch("dispatch.executor.subprocess.run") as mock_run:
            result = execute_dispatch(self.root, preview_path, operator_execute=True, dry_run=False)
            mock_run.assert_not_called()
        self.assertFalse(result.executed)
        self.assertFalse(result.execution_allowed)

    def test_malformed_plan_blocks_execute(self) -> None:
        bad = self.root / "runtime/orchestrator/bad_plan.json"
        bad.write_text("{not valid json", encoding="utf-8")
        result = self._gate(_base_preview(plan_path=str(bad.relative_to(self.root))), execute=True)
        self.assertFalse(result.execution_allowed)
        preview_path = self._make_preview_path()
        self._update_preview_plan_path(preview_path, str(bad.relative_to(self.root)))
        with patch("dispatch.executor.subprocess.run") as mock_run:
            result = execute_dispatch(self.root, preview_path, operator_execute=True, dry_run=False)
            mock_run.assert_not_called()
        self.assertFalse(result.executed)
        self.assertFalse(result.execution_allowed)

    def test_missing_live_task_blocks_execute(self) -> None:
        (self.root / "tasks/active/T-M2.yaml").unlink()
        result = self._gate(_base_preview(), execute=True)
        self.assertFalse(result.execution_allowed)
        self.assertTrue(
            any("preview freshness cannot be verified" in r or "stale" in r for r in result.blocked_reasons)
        )

    def test_missing_adapter_blocks(self) -> None:
        result = evaluate_execution_gates(
            self.root,
            {**_base_preview(), "working_directory": str(self.root)},
            adapter=None,
            cli_inventory={"tools": [{"name": "python", "available": True, "path": sys.executable}]},
            dry_run=True,
        )
        self.assertFalse(result.execution_allowed)

    def test_stale_plan_blocks_execute(self) -> None:
        preview_path = self._make_preview_path()
        preview = json.loads(preview_path.read_text(encoding="utf-8"))
        task = yaml.safe_load((self.root / "tasks/active/T-M2.yaml").read_text(encoding="utf-8"))
        task["risk_level"] = "high"
        (self.root / "tasks/active/T-M2.yaml").write_text(yaml.safe_dump(task, sort_keys=False), encoding="utf-8")
        result = self._gate(preview, execute=True)
        self.assertFalse(result.execution_allowed)
        self.assertTrue(any("stale" in r.lower() for r in result.blocked_reasons))

    def test_valid_unchanged_plan_passes_dry_run(self) -> None:
        result = self._gate(_base_preview(), dry_run=True)
        self.assertTrue(result.execution_allowed)
        self.assertFalse(any("preview freshness cannot be verified" in r for r in result.blocked_reasons))

    def test_dry_run_unverifiable_plan_warns_without_subprocess(self) -> None:
        preview_path = self._make_preview_path()
        (self.root / "runtime/orchestrator/latest_plan.json").unlink()
        self._update_preview_plan_path(preview_path, "runtime/orchestrator/missing_plan.json")
        with patch("dispatch.executor.subprocess.run") as mock_run:
            result = execute_dispatch(self.root, preview_path, dry_run=True)
            mock_run.assert_not_called()
        self.assertFalse(result.executed)
        gate = self._gate(_base_preview(plan_path="runtime/orchestrator/missing_plan.json"), dry_run=True)
        self.assertTrue(any("preview freshness cannot be verified" in w for w in gate.warnings))

    def test_execute_unverifiable_plan_cannot_soft_fail(self) -> None:
        (self.root / "runtime/orchestrator/latest_plan.json").unlink()
        result = self._gate(_base_preview(plan_path="runtime/orchestrator/missing_plan.json"), execute=True)
        self.assertFalse(result.execution_allowed)
        self.assertTrue(any("preview freshness cannot be verified" in r for r in result.blocked_reasons))
        self.assertFalse(any("preview freshness cannot be verified" in w for w in result.warnings))


class L3EventEmitRegressionTests(ReviewFixFixtureMixin, unittest.TestCase):
    def test_central_emit_failure_surfaces_event_emit_errors(self) -> None:
        preview_path = self._make_preview_path()
        with patch("protocol.emit_event.append_event", side_effect=RuntimeError("central down")):
            result = execute_dispatch(self.root, preview_path, dry_run=True)
        self.assertTrue(result.event_emit_errors)
        self.assertTrue(result.execution_allowed)
        saved = json.loads((self.root / result.result_path).read_text(encoding="utf-8"))
        self.assertTrue(saved["event_emit_errors"])
        run_dir = self.root / "runtime" / "dispatch" / "runs" / result.run_id
        events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn("event_emit_error", events)

    def test_nested_emit_failures_do_not_recurse(self) -> None:
        preview_path = self._make_preview_path()

        def selective_append(run_dir, event):
            if isinstance(event, dict) and event.get("type") == "event_emit_error":
                raise RuntimeError("local down")
            return _real_append_run_event(run_dir, event)

        with patch("protocol.emit_event.append_event", side_effect=RuntimeError("central down")):
            with patch("dispatch.executor.append_run_event", side_effect=selective_append):
                result = execute_dispatch(self.root, preview_path, dry_run=True)
        self.assertGreaterEqual(len(result.event_emit_errors), 1)
        self.assertIn("central down", result.event_emit_errors[0])
        self.assertTrue(any("local down" in e for e in result.event_emit_errors))
        self.assertTrue(result.execution_allowed)


class HandoffVerificationProtocolTests(unittest.TestCase):
    def test_missing_open_questions_fails_handoff_validation(self) -> None:
        text = _sample_v2_handoff(impl_sha="a" * 40).replace("## Open Questions\n- none\n\n", "")
        errors: list[str] = []
        validate_mod.validate_handoffs(errors)
        # validate_handoffs scans all handoffs; test our synthetic content via section check
        for section in validate_mod.REQUIRED_HANDOFF_SECTIONS:
            if section not in text:
                errors.append(f"missing {section}")
        self.assertTrue(any("Open Questions" in e for e in errors))

    def test_complete_handoff_sections_pass(self) -> None:
        text = _sample_v2_handoff(impl_sha="a" * 40)
        for section in validate_mod.REQUIRED_HANDOFF_SECTIONS:
            self.assertIn(section, text)

    def test_v2_handoff_with_complete_verification_passes(self) -> None:
        text = _sample_v2_handoff(impl_sha="a" * 40)
        errors: list[str] = []
        validate_mod.validate_handoff_verification_block("handoffs/sample.md", text, errors)
        self.assertEqual(errors, [])

    def test_v2_handoff_missing_field_fails(self) -> None:
        text = _sample_v2_handoff(impl_sha="a" * 40).replace("remote_head_sha:", "remote_head_missing:")
        errors: list[str] = []
        validate_mod.validate_handoff_verification_block("handoffs/sample.md", text, errors)
        self.assertTrue(any("remote_head_sha" in e for e in errors))

    def test_historical_v1_handoff_without_verification_passes(self) -> None:
        text = (
            "# Handoff: T-OLD\n**From:** composer\n**To:** claude\n**Date:** 2026-05-22\n"
            "**Task Status After Handoff:** review\n\n## What I Did\n- x\n## What Remains\n- y\n"
            "## Decisions Made\n- z\n## Open Questions\n- q\n## How to Verify My Work\n- v\n"
            "## Risks / Caveats\n- r\n## Recommended Next Action for Receiver\n- n\n"
        )
        errors: list[str] = []
        validate_mod.validate_handoff_verification_block("handoffs/T-OLD.md", text, errors)
        self.assertEqual(errors, [])

    def test_v2_invalid_sha_format_fails(self) -> None:
        text = _sample_v2_handoff(impl_sha="not-a-sha")
        errors: list[str] = []
        validate_mod.validate_handoff_verification_block("handoffs/sample.md", text, errors)
        self.assertTrue(any("implementation_sha" in e and "40-character" in e for e in errors))

    def test_v2_nonzero_test_exit_code_fails(self) -> None:
        text = _sample_v2_handoff(impl_sha="a" * 40, test_exit_code="1")
        errors: list[str] = []
        validate_mod.validate_handoff_verification_block("handoffs/sample.md", text, errors)
        self.assertTrue(any("test_exit_code" in e for e in errors))

    def test_v2_nonzero_validator_exit_code_fails(self) -> None:
        text = _sample_v2_handoff(impl_sha="a" * 40, validator_exit_code="1")
        errors: list[str] = []
        validate_mod.validate_handoff_verification_block("handoffs/sample.md", text, errors)
        self.assertTrue(any("validator_exit_code" in e for e in errors))

    def test_final_remote_recorded_mismatch_fails(self) -> None:
        text = _sample_v2_handoff(impl_sha="a" * 40)
        text = text.replace("remote_head_sha: " + "b" * 40, "remote_head_sha: " + "c" * 40)
        errors: list[str] = []
        validate_mod.validate_handoff_verification_block("handoffs/sample.md", text, errors)
        self.assertTrue(any("final_head_sha" in e and "remote_head_sha" in e for e in errors))

    def test_tests_commit_not_equal_implementation_sha_fails(self) -> None:
        from scripts.repository_verification import validate_repository_verification

        verification = {
            "implementation_sha": "a" * 40,
            "tests_commit_sha": "b" * 40,
            "final_head_sha": "b" * 40,
            "remote_head_sha": "b" * 40,
            "test_exit_code": "0",
            "validator_exit_code": "0",
        }
        result = validate_repository_verification(verification, rel="test")
        self.assertEqual(result.status, "failed")
        self.assertTrue(any("implementation_sha" in e for e in result.errors))

    def test_allowlisted_post_test_changes_pass_with_git_context(self) -> None:
        from scripts import repository_verification as rv
        from scripts.repository_verification import validate_repository_verification

        impl = "a" * 40
        final = "b" * 40
        allowed = sorted(
            p for p in rv.POST_TEST_ALLOWLIST_EXACT if p.startswith("docs/REVIEW_COMPOSER_")
        )[0]
        verification = {
            "implementation_sha": impl,
            "tests_commit_sha": impl,
            "final_head_sha": final,
            "remote_head_sha": final,
            "test_exit_code": "0",
            "validator_exit_code": "0",
            "post_test_diff_policy": "verification-only-allowlist-v3",
            "post_test_files": allowed,
        }
        result = validate_repository_verification(
            verification,
            actual_head_sha=final,
            changed_files_after_tests=[allowed],
            rel="test",
        )
        self.assertEqual(result.status, "verified")

    def test_code_file_changed_after_tests_fails(self) -> None:
        from scripts.repository_verification import validate_repository_verification

        impl = "a" * 40
        final = "b" * 40
        verification = {
            "implementation_sha": impl,
            "tests_commit_sha": impl,
            "final_head_sha": final,
            "remote_head_sha": final,
            "test_exit_code": "0",
            "validator_exit_code": "0",
        }
        result = validate_repository_verification(
            verification,
            actual_head_sha=final,
            changed_files_after_tests=["dispatch/executor.py"],
            rel="test",
        )
        self.assertEqual(result.status, "failed")
        self.assertIn("dispatch/executor.py", result.post_test_violations)

    def test_test_file_changed_after_tests_fails(self) -> None:
        from scripts.repository_verification import validate_repository_verification

        impl = "a" * 40
        final = "b" * 40
        result = validate_repository_verification(
            {
                "implementation_sha": impl,
                "tests_commit_sha": impl,
                "final_head_sha": final,
                "remote_head_sha": final,
                "test_exit_code": "0",
                "validator_exit_code": "0",
            },
            actual_head_sha=final,
            changed_files_after_tests=["tests/test_foo.py"],
            rel="test",
        )
        self.assertEqual(result.status, "failed")

    def test_validator_script_changed_after_tests_fails(self) -> None:
        from scripts.repository_verification import validate_repository_verification

        impl = "a" * 40
        final = "b" * 40
        result = validate_repository_verification(
            {
                "implementation_sha": impl,
                "tests_commit_sha": impl,
                "final_head_sha": final,
                "remote_head_sha": final,
                "test_exit_code": "0",
                "validator_exit_code": "0",
            },
            actual_head_sha=final,
            changed_files_after_tests=["scripts/validate.py"],
            rel="test",
        )
        self.assertEqual(result.status, "failed")

    def test_explicit_allowlist_post_test_changes_pass(self) -> None:
        from scripts import repository_verification as rv
        from scripts.repository_verification import validate_repository_verification

        impl = "a" * 40
        final = "b" * 40
        handoff = sorted(p for p in rv.POST_TEST_ALLOWLIST_EXACT if p.startswith("handoffs/"))[0]
        self_review = sorted(
            p for p in rv.POST_TEST_ALLOWLIST_EXACT if p.startswith("docs/REVIEW_COMPOSER_")
        )[0]
        allowed = [
            "runtime/unittest_last_run.txt",
            handoff,
            self_review,
        ]
        result = validate_repository_verification(
            {
                "implementation_sha": impl,
                "tests_commit_sha": impl,
                "final_head_sha": final,
                "remote_head_sha": final,
                "test_exit_code": "0",
                "validator_exit_code": "0",
                "post_test_diff_policy": "verification-only-allowlist-v3",
                "post_test_files": ", ".join(allowed),
            },
            actual_head_sha=final,
            changed_files_after_tests=allowed,
            rel="test",
        )
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.post_test_violations, [])

    def test_decisions_change_after_tests_fails(self) -> None:
        from scripts.repository_verification import validate_repository_verification

        impl = "a" * 40
        final = "b" * 40
        result = validate_repository_verification(
            {
                "implementation_sha": impl,
                "tests_commit_sha": impl,
                "final_head_sha": final,
                "remote_head_sha": final,
                "test_exit_code": "0",
                "validator_exit_code": "0",
            },
            actual_head_sha=final,
            changed_files_after_tests=["decisions/INDEX.md"],
            rel="test",
        )
        self.assertEqual(result.status, "failed")
        self.assertIn("decisions/INDEX.md", result.post_test_violations)


def _sample_v2_handoff(
    *,
    impl_sha: str,
    test_exit_code: str = "0",
    validator_exit_code: str = "0",
) -> str:
    final_sha = "b" * 40 if impl_sha != "b" * 40 else "c" * 40
    if len(impl_sha) != 40:
        final_sha = "b" * 40
    return f"""# Handoff: T-SAMPLE
**From:** composer
**To:** claude
**Date:** 2026-06-20
**Task Status After Handoff:** review
**Handoff Protocol:** v2

## What I Did
- sample

## What Remains
- none

## Decisions Made
- sample

## Open Questions
- none

## How to Verify My Work
- run tests

## Risks / Caveats
- none

## Recommended Next Action for Receiver
- review

## Repository Verification

repo_root: C:/Users/gabot/agentic-os
branch: agent/composer/T-PHASE3-3-2-CLOSEOUT-FIXES
base_sha: {"5" * 40}
implementation_sha: {impl_sha}
tests_commit_sha: {impl_sha}
final_head_sha: {final_sha}
remote_head_sha: {final_sha}
git_status_clean: true
validator_commit_sha: {impl_sha}
test_count: 300
test_exit_code: {test_exit_code}
validator_exit_code: {validator_exit_code}
post_test_diff_policy: docs-only-allowlist-v2
post_test_files: docs/foo.md
working_copy_path: C:/Users/gabot/agentic-os
"""


if __name__ == "__main__":
    unittest.main()