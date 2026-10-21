"""Focused clone provenance and deploy state-root regression coverage."""
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout, redirect_stderr
from types import SimpleNamespace
from scripts import verify_repository_verification as verifier

from scripts import repository_verification as rv
from scripts import run_tests, run_supervisor_layers, run_orchestrator, run_claude_event_consumer
from scripts.state_root import resolve_state_root
from tests.test_phase3_4_1_integrity_closeout import _artifact, _verification, _sha


class ProvenanceTests(unittest.TestCase):
    def check_artifact(self, artifact=None, verification=None, ancestor=True):
        return rv.validate_test_artifact(
            artifact or _artifact(), verification=verification or _verification(),
            actual_head_sha=_sha("f"), artifact_exists=True,
            is_ancestor=lambda a, b: ancestor)[1]

    def test_clone_path_with_same_identity_passes(self):
        self.assertEqual(self.check_artifact(_artifact(repo_root="/clone", artifact_origin_path="/clone")), "verified")

    def test_foreign_identity_fails(self):
        self.assertEqual(self.check_artifact(_artifact(repo_identity="foreign")), "failed")

    def test_exact_sha_and_reachability_required(self):
        self.assertEqual(self.check_artifact(_artifact(commit_full=_sha("a"))), "failed")
        self.assertEqual(self.check_artifact(ancestor=False), "failed")

    def test_output_tampering_fails(self):
        self.assertEqual(self.check_artifact(_artifact(computed_output_sha256="tampered")), "failed")

    def test_unlisted_failure_fails(self):
        self.assertEqual(self.check_artifact(_artifact(exit_code="1", computed_result="failed", computed_failures='["test_bad (suite.Case)"]'),
                         _verification(test_exit_code="1")), "failed")

    def test_listed_failure_with_true_exit_passes(self):
        failure = "test_cp1252 (suite.Case)"
        artifact = _artifact(exit_code="1", computed_result="failed", computed_failures=json.dumps([failure]))
        verification = _verification(test_exit_code="1", known_exempt_failures=json.dumps([failure]))
        self.assertEqual(self.check_artifact(artifact, verification), "verified")
        self.assertEqual(self.check_artifact(artifact, dict(verification, test_exit_code="0")), "failed")

    def test_edited_evidence_fails(self):
        original = "## Repository Verification\ntests_commit_sha: " + _sha("e") + "\n"
        changed = original + "test_count: 2\n"
        artifact = _artifact(evidence_block_sha256=rv.evidence_block_hash(original))
        self.assertEqual(self.check_artifact(artifact, _verification(evidence_block_sha256=rv.evidence_block_hash(changed))), "failed")

    def test_writer_loader_round_trip_and_raw_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff = root / "handoff.md"
            handoff.write_text("## Repository Verification\ntest_count: 1\n", encoding="utf-8")
            output = "Ran 1 test in 0.01s\n\nOK\n"
            with patch.object(run_tests, "RESULT_PATH", root / rv.UNITTEST_ARTIFACT_REL), patch.object(run_tests, "repository_identity", return_value="identity"):
                run_tests._write_result(0, output, handoff=handoff, command_line=["python", "-m", "unittest"])
            artifact, exists = rv.load_unittest_artifact(root)
            self.assertTrue(exists)
            self.assertEqual(artifact["raw_output_sha256"], artifact["computed_output_sha256"])
            self.assertEqual(artifact["dependency_install"], "performed")
            self.assertEqual(artifact["computed_test_count"], "1")
            self.assertEqual(artifact["computed_result"], "passed")
            self.assertEqual(artifact["evidence_block_sha256"], rv.evidence_block_hash(handoff.read_text()))
            path = root / rv.UNITTEST_ARTIFACT_REL
            path.write_bytes(path.read_bytes() + b"tampered")
            tampered, _ = rv.load_unittest_artifact(root)
            self.assertNotEqual(tampered["raw_output_sha256"], tampered["computed_output_sha256"])

    def test_skip_install_requires_reason(self):
        for extra in ([], ["--skip-install-reason", " "],
                      ["--skip-install-reason", "bad\nreason"]):
            with self.subTest(extra=extra), patch("sys.argv", ["run_tests", "--handoff", "unused", "--skip-install", *extra]), redirect_stderr(io.StringIO()), patch.object(run_tests.subprocess, "run") as run:
                with self.assertRaises(SystemExit) as raised:
                    run_tests.main()
                self.assertEqual(raised.exception.code, 2)
                run.assert_not_called()

    def test_main_install_and_skip_paths(self):
        for skip in (False, True):
            with self.subTest(skip=skip):
                argv = ["run_tests", "--handoff", "unused"]
                if skip:
                    argv += ["--skip-install", "--skip-install-reason", "host bootstrap blocker"]
                tests = SimpleNamespace(returncode=0, stdout=b"Ran 1 test in 0.01s\nOK\n", stderr=b"", args=["unittest"])
                install = SimpleNamespace(returncode=0)
                with patch("sys.argv", argv), patch.object(run_tests, "_git_head", return_value="head"), patch.object(run_tests, "REQUIREMENTS") as requirements, patch.object(run_tests.subprocess, "run", side_effect=[tests] if skip else [install, tests]) as run, patch.object(run_tests, "_write_result") as write, redirect_stdout(io.StringIO()):
                    requirements.exists.return_value = True
                    self.assertEqual(run_tests.main(), 0)
                    self.assertEqual(run.call_count, 1 if skip else 2)
                    if not skip:
                        self.assertEqual(run.call_args_list[0].args[0][1:4], ["-m", "pip", "install"])
                    self.assertEqual(write.call_args.kwargs["skip_install_reason"], "host bootstrap blocker" if skip else None)

    def test_skip_reason_is_hashed_and_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff = root / "handoff.md"
            handoff.write_text("## Repository Verification\ntest_count: 1\n", encoding="utf-8")
            with patch.object(run_tests, "RESULT_PATH", root / rv.UNITTEST_ARTIFACT_REL), patch.object(run_tests, "repository_identity", return_value="identity"):
                run_tests._write_result(0, "Ran 1 test in 0.01s\nOK\n", handoff=handoff, skip_install_reason="host blocker")
            artifact, _ = rv.load_unittest_artifact(root)
            self.assertEqual(artifact["dependency_install"], "skipped")
            self.assertEqual(artifact["dependency_install_reason"], "host blocker")
            self.assertEqual(artifact["raw_output_sha256"], artifact["computed_output_sha256"])
            result = SimpleNamespace(artifact_status="", git_ancestry_status="", post_test_diff_status="", validator_status="", status="verified")
            report = io.StringIO()
            with redirect_stdout(report):
                verifier._print_result(result, artifact)
            self.assertIn("Dependency install: skipped (host blocker)", report.getvalue())
            path = root / rv.UNITTEST_ARTIFACT_REL
            original = path.read_bytes()
            for count in (1, 2):
                path.write_bytes(original.replace(b"host blocker", b"edited reason", count))
                edited, _ = rv.load_unittest_artifact(root)
                errors, status = rv.validate_test_artifact(edited, verification=_verification(), actual_head_sha=_sha("f"), artifact_exists=True, is_ancestor=lambda a, b: True)
                self.assertEqual(status, "failed")
                self.assertTrue(any("dependency_install_reason mismatch" in error or "raw_output_sha256 mismatch" in error for error in errors))

    def test_failure_summary_round_trip_requires_every_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff = root / "handoff.md"
            handoff.write_text("## Repository Verification\nknown_exempt_failures: []\n", encoding="utf-8")
            output = b"FAIL: test_cp1252 (suite.Case)\r\nRan 1 test in 0.01s\r\nFAILED (failures=1)\r\n"
            with patch.object(run_tests, "RESULT_PATH", root / rv.UNITTEST_ARTIFACT_REL), patch.object(run_tests, "repository_identity", return_value="identity"):
                run_tests._write_result(1, output, handoff=handoff)
            artifact, _ = rv.load_unittest_artifact(root)
            self.assertEqual(artifact["computed_result"], "failed")
            self.assertEqual(json.loads(artifact["computed_failures"]), ["test_cp1252 (suite.Case)"])
            verification = _verification(test_count="1", test_exit_code="1", known_exempt_failures='["test_cp1252 (suite.Case)"]', evidence_block_sha256=rv.evidence_block_hash(handoff.read_text()))
            artifact["commit_full"] = _sha("e")
            self.assertEqual(self.check_artifact(artifact, verification), "verified")
            self.assertEqual(self.check_artifact(artifact, dict(verification, known_exempt_failures="[]")), "failed")

    def test_real_local_clone_identity_and_foreign_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            def git(cwd, *args):
                result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)
                if result.returncode:
                    raise AssertionError(result.stderr.decode(errors="replace"))
                return result
            git(source, "init")
            git(source, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "root")
            git(source, "remote", "add", "origin", "https://example.invalid/canonical.git")
            clone = root / "clone"
            # Duplicate the local Git object store without invoking shell-based transport.
            shutil.copytree(source, clone)
            git(clone, "remote", "set-url", "origin", str(source))
            self.assertEqual(rv.repository_identity(source), rv.repository_identity(clone))
            git(clone, "remote", "set-url", "origin", "https://example.invalid/foreign.git")
            self.assertNotEqual(rv.repository_identity(source), rv.repository_identity(clone))
            foreign = root / "foreign"
            foreign.mkdir()
            git(foreign, "init")
            git(foreign, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "foreign root")
            git(foreign, "remote", "add", "origin", "https://example.invalid/canonical.git")
            self.assertNotEqual(rv.repository_identity(source), rv.repository_identity(foreign))


class StateRootTests(unittest.TestCase):
    def test_default_flag_env_and_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("default", "flag", "env"):
                for child in ("runtime", "agents"):
                    (root / name / child).mkdir(parents=True)
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(resolve_state_root(root / "default"), root / "default")
            with patch.dict(os.environ, {"AGENTIC_OS_STATE_ROOT": str(root / "env")}):
                self.assertEqual(resolve_state_root(root / "default"), root / "env")
                self.assertEqual(resolve_state_root(root / "default", root / "flag"), root / "flag")
                with self.assertRaises(ValueError):
                    resolve_state_root(root / "default", root / "missing")

    def test_layer_parent_uses_state_and_children_use_deployed_code(self):
        root = Path(__file__).resolve().parents[1]
        with patch("sys.argv", ["run_supervisor_layers", "--state-root", str(root)]), patch.object(run_supervisor_layers, "LayerSupervisor") as supervisor:
            supervisor.return_value.run.return_value = 0
            self.assertEqual(run_supervisor_layers.main(), 0)
            selected, commands = supervisor.call_args.args
            self.assertEqual(selected, root)
            for command in commands.values():
                self.assertEqual(command[-2:], ["--state-root", str(root)])
                self.assertTrue(command[1].startswith(str(run_supervisor_layers.REPO_ROOT)))

    def test_entrypoints_select_state_root(self):
        root = Path(__file__).resolve().parents[1]
        with patch("sys.argv", ["run_orchestrator", "--once", "--state-root", str(root)]), patch.object(run_orchestrator, "process_once", return_value={"status": "idle"}) as process:
            self.assertEqual(run_orchestrator.main(), 0)
            self.assertEqual(process.call_args.args[0], root)
        with patch("sys.argv", ["consumer", "--once", "--state-root", str(root)]), patch.object(run_claude_event_consumer, "ClaudeEventConsumer") as consumer, patch.object(run_claude_event_consumer, "RotatingLogWriter") as logger:
            consumer.return_value.process_once.return_value = {"status": "idle"}
            self.assertEqual(run_claude_event_consumer.main(), 0)
            self.assertEqual(consumer.call_args.args[0], root)
            self.assertEqual(logger.call_args.args[0], root / "logs/claude-event-consumer.jsonl")

