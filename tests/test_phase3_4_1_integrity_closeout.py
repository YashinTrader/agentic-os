"""Phase 3.4.1 integrity closeout — artifact cross-check, strict allowlist, validator-at-HEAD."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts import repository_verification as rv  # noqa: E402


def _sha(ch: str = "a") -> str:
    return ch * 40


def _verification(**overrides) -> dict:
    base = {
        "implementation_sha": _sha("e"),
        "tests_commit_sha": _sha("e"),
        "final_head_sha": _sha("f"),
        "remote_head_sha": _sha("f"),
        "test_count": "350",
        "test_exit_code": "0",
        "validator_exit_code": "0",
        "repo_root": "C:/Users/gabot/agentic-os",
        "post_test_diff_policy": "verification-only-allowlist-v3",
        "post_test_files": "runtime/unittest_last_run.txt",
    }
    base.update(overrides)
    return base


def _current_closeout_handoff() -> str:
    handoffs = sorted(
        p for p in rv.POST_TEST_ALLOWLIST_EXACT if p.startswith("handoffs/")
    )
    if not handoffs:
        raise AssertionError("POST_TEST_ALLOWLIST_EXACT must include a handoffs/ path")
    return handoffs[0]


def _artifact(**overrides) -> dict:
    base = {
        "commit_full": _sha("e"),
        "test_count": "350",
        "exit_code": "0",
        "repo_root": "C:/Users/gabot/agentic-os",
    }
    base.update(overrides)
    return base


class ParseArtifactTests(unittest.TestCase):
    def test_parse_valid_artifact(self) -> None:
        text = (
            "timestamp: 2026-06-20T12:00:00Z\n"
            f"repo_root: C:/Users/gabot/agentic-os\n"
            "commit: ecec766\n"
            f"commit_full: {_sha('e')}\n"
            "python: /usr/bin/python\n"
            "test_count: 350\n"
            "exit_code: 0\n"
            "--- tail ---\n"
            "OK\n"
        )
        parsed = rv.parse_unittest_last_run(text)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["commit_full"], _sha("e"))
        self.assertEqual(parsed["test_count"], "350")

    def test_malformed_artifact_returns_none(self) -> None:
        self.assertIsNone(rv.parse_unittest_last_run("timestamp: x\n"))


class PostTestAllowlistTests(unittest.TestCase):
    def test_decisions_adr_not_allowlisted(self) -> None:
        self.assertFalse(rv.is_post_test_allowlisted("decisions/ADR-0025-worktree-allocator-mvp.md"))

    def test_decisions_index_not_allowlisted(self) -> None:
        self.assertFalse(rv.is_post_test_allowlisted("decisions/INDEX.md"))

    def test_artifact_only_allowlisted(self) -> None:
        self.assertTrue(rv.is_post_test_allowlisted("runtime/unittest_last_run.txt"))

    def test_closeout_handoff_allowlisted(self) -> None:
        self.assertTrue(rv.is_post_test_allowlisted(_current_closeout_handoff()))

    def test_unrelated_docs_not_allowlisted(self) -> None:
        self.assertFalse(rv.is_post_test_allowlisted("docs/PHASE_3_5_PLAN.md"))

    def test_decisions_adr_change_fails(self) -> None:
        result = rv.validate_repository_verification(
            _verification(),
            actual_head_sha=_sha("f"),
            changed_files_after_tests=["decisions/ADR-0025-worktree-allocator-mvp.md"],
            rel="test",
        )
        self.assertEqual(result.status, "failed")
        self.assertIn("decisions/ADR-0025-worktree-allocator-mvp.md", result.post_test_violations)

    def test_decisions_index_change_fails(self) -> None:
        result = rv.validate_repository_verification(
            _verification(),
            actual_head_sha=_sha("f"),
            changed_files_after_tests=["decisions/INDEX.md"],
            rel="test",
        )
        self.assertEqual(result.status, "failed")

    def test_code_change_fails(self) -> None:
        result = rv.validate_repository_verification(
            _verification(),
            actual_head_sha=_sha("f"),
            changed_files_after_tests=["dispatch/executor.py"],
            rel="test",
        )
        self.assertEqual(result.status, "failed")

    def test_script_change_fails(self) -> None:
        result = rv.validate_repository_verification(
            _verification(),
            actual_head_sha=_sha("f"),
            changed_files_after_tests=["scripts/validate.py"],
            rel="test",
        )
        self.assertEqual(result.status, "failed")

    def test_schema_change_fails(self) -> None:
        result = rv.validate_repository_verification(
            _verification(),
            actual_head_sha=_sha("f"),
            changed_files_after_tests=["schemas/signed_approval_record.schema.json"],
            rel="test",
        )
        self.assertEqual(result.status, "failed")

    def test_adapter_registry_change_fails(self) -> None:
        result = rv.validate_repository_verification(
            _verification(),
            actual_head_sha=_sha("f"),
            changed_files_after_tests=["agents/adapter_registry.yaml"],
            rel="test",
        )
        self.assertEqual(result.status, "failed")

    def test_event_vocabulary_change_fails(self) -> None:
        result = rv.validate_repository_verification(
            _verification(),
            actual_head_sha=_sha("f"),
            changed_files_after_tests=["protocol/event_types.py"],
            rel="test",
        )
        self.assertEqual(result.status, "failed")

    def test_artifact_only_change_passes(self) -> None:
        result = rv.validate_repository_verification(
            _verification(),
            actual_head_sha=_sha("f"),
            changed_files_after_tests=["runtime/unittest_last_run.txt"],
            rel="test",
        )
        self.assertEqual(result.status, "verified")

    def test_closeout_handoff_only_passes(self) -> None:
        handoff = _current_closeout_handoff()
        result = rv.validate_repository_verification(
            _verification(post_test_files=handoff),
            actual_head_sha=_sha("f"),
            changed_files_after_tests=[handoff],
            rel="test",
        )
        self.assertEqual(result.status, "verified")


class ArtifactCrossCheckTests(unittest.TestCase):
    def test_correct_artifact_passes(self) -> None:
        errors, status = rv.validate_test_artifact(
            _artifact(),
            verification=_verification(),
            actual_head_sha=_sha("f"),
            artifact_exists=True,
            rel="test",
            is_ancestor=lambda a, d: True,
        )
        self.assertEqual(status, "verified")
        self.assertEqual(errors, [])

    def test_missing_artifact_fails(self) -> None:
        errors, status = rv.validate_test_artifact(
            None,
            verification=_verification(),
            actual_head_sha=_sha("f"),
            artifact_exists=False,
            rel="test",
        )
        self.assertEqual(status, "missing")
        self.assertTrue(any("test artifact missing" in e for e in errors))

    def test_malformed_artifact_fails(self) -> None:
        errors, status = rv.validate_test_artifact(
            {"commit_full": "bad"},
            verification=_verification(),
            actual_head_sha=_sha("f"),
            artifact_exists=True,
            rel="test",
        )
        self.assertEqual(status, "malformed")

    def test_stale_rebased_commit_fails(self) -> None:
        errors, status = rv.validate_test_artifact(
            _artifact(commit_full=_sha("0")),
            verification=_verification(),
            actual_head_sha=_sha("f"),
            artifact_exists=True,
            rel="test",
            is_ancestor=lambda a, d: a == _sha("e"),
        )
        self.assertEqual(status, "failed")
        self.assertTrue(any("artifact commit does not match" in e for e in errors))

    def test_count_mismatch_fails(self) -> None:
        errors, status = rv.validate_test_artifact(
            _artifact(test_count="100"),
            verification=_verification(test_count="350"),
            actual_head_sha=_sha("f"),
            artifact_exists=True,
            rel="test",
            is_ancestor=lambda a, d: True,
        )
        self.assertTrue(any("artifact test count mismatch" in e for e in errors))

    def test_exit_mismatch_fails(self) -> None:
        errors, status = rv.validate_test_artifact(
            _artifact(exit_code="1"),
            verification=_verification(),
            actual_head_sha=_sha("f"),
            artifact_exists=True,
            rel="test",
            is_ancestor=lambda a, d: True,
        )
        self.assertTrue(any("artifact exit code mismatch" in e for e in errors))

    def test_wrong_repo_path_fails(self) -> None:
        errors, status = rv.validate_test_artifact(
            _artifact(repo_root="C:/Users/gabot/Documents/Codex/agentic-os"),
            verification=_verification(),
            actual_head_sha=_sha("f"),
            artifact_exists=True,
            rel="test",
            is_ancestor=lambda a, d: True,
        )
        self.assertTrue(any("canonical clone" in e for e in errors))

    def test_not_ancestor_fails(self) -> None:
        errors, status = rv.validate_test_artifact(
            _artifact(),
            verification=_verification(),
            actual_head_sha=_sha("f"),
            artifact_exists=True,
            rel="test",
            is_ancestor=lambda a, d: False,
        )
        self.assertTrue(any("artifact commit not reachable" in e for e in errors))


class ValidatorAtHeadTests(unittest.TestCase):
    def test_validator_exit_zero_passes(self) -> None:
        errors, status, code = rv.validate_validator_at_head(
            rv.ValidatorRunResult(exit_code=0, stdout="ok", stderr=""),
            verification=_verification(),
            rel="test",
        )
        self.assertEqual(status, "passed")
        self.assertEqual(code, 0)
        self.assertEqual(errors, [])

    def test_validator_exit_one_fails(self) -> None:
        errors, status, code = rv.validate_validator_at_head(
            rv.ValidatorRunResult(exit_code=1, stdout="", stderr="fail"),
            verification=_verification(),
            rel="test",
        )
        self.assertEqual(status, "failed")
        self.assertEqual(code, 1)
        self.assertTrue(errors)

    def test_validator_timeout_fails(self) -> None:
        errors, status, _ = rv.validate_validator_at_head(
            rv.ValidatorRunResult(exit_code=-1, stdout="", stderr="", error="validator timeout"),
            verification=_verification(),
            rel="test",
        )
        self.assertEqual(status, "failed")
        self.assertTrue(any("validator timeout" in e for e in errors))

    def test_validator_missing_fails(self) -> None:
        errors, status, _ = rv.validate_validator_at_head(
            rv.ValidatorRunResult(exit_code=-1, stdout="", stderr="", error="validator missing"),
            verification=_verification(),
            rel="test",
        )
        self.assertTrue(any("validator missing" in e for e in errors))

    def test_declared_validator_conflict_fails(self) -> None:
        errors, status, _ = rv.validate_validator_at_head(
            rv.ValidatorRunResult(exit_code=0, stdout="", stderr=""),
            verification=_verification(validator_exit_code="1"),
            rel="test",
        )
        self.assertTrue(any("validator_exit_code" in e for e in errors))

    @patch("scripts.repository_verification.subprocess.run")
    def test_run_validator_uses_sys_executable_and_no_shell(self, mock_run) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Validation passed.\n", stderr=""
        )
        result = rv.run_validator_at_head(REPO_ROOT)
        self.assertEqual(result.exit_code, 0)
        call = mock_run.call_args
        self.assertEqual(call.kwargs.get("shell"), False)
        argv = call.args[0]
        self.assertEqual(argv[0], sys.executable)
        self.assertTrue(Path(argv[1]).name == "validate.py")
        self.assertTrue("scripts" in Path(argv[1]).parts)


class EndToEndVerificationTests(unittest.TestCase):
    def test_truthful_handoff_verified(self) -> None:
        result = rv.validate_repository_verification(
            _verification(),
            actual_head_sha=_sha("f"),
            changed_files_after_tests=["runtime/unittest_last_run.txt"],
            test_artifact=_artifact(),
            artifact_exists=True,
            artifact_is_ancestor=lambda a, d: True,
            validator_result=rv.ValidatorRunResult(exit_code=0, stdout="", stderr=""),
            run_artifact_checks=True,
            run_validator_checks=True,
            rel="test",
        )
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.artifact_status, "verified")
        self.assertEqual(result.validator_status, "passed")

    def test_false_green_handoff_fails(self) -> None:
        result = rv.validate_repository_verification(
            _verification(test_count="999"),
            actual_head_sha=_sha("f"),
            changed_files_after_tests=["runtime/unittest_last_run.txt"],
            test_artifact=_artifact(test_count="350"),
            artifact_exists=True,
            artifact_is_ancestor=lambda a, d: True,
            validator_result=rv.ValidatorRunResult(exit_code=0, stdout="", stderr=""),
            run_artifact_checks=True,
            run_validator_checks=True,
            rel="test",
        )
        self.assertEqual(result.status, "failed")


if __name__ == "__main__":
    unittest.main()