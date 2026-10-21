"""Exercise closeout ordering with real Git and only the unittest child mocked."""

import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import handoff_verification_block as blocks
from scripts import repository_verification as rv
from scripts import run_tests
from scripts import verify_repository_verification as verifier
from tests.test_phase3_4_1_integrity_closeout import _artifact, _verification, _sha


class AchievableSealTests(unittest.TestCase):
    def test_real_git_closeout_and_every_sealed_field_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            real_run = subprocess.run

            def git(*args):
                return real_run(["git", *args], cwd=root, capture_output=True,
                                text=True, check=True).stdout.strip()

            def commit(message):
                git("add", ".")
                git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "commit", "-m", message)
                return git("rev-parse", "HEAD")

            git("init")
            git("remote", "add", "origin", "https://example.invalid/seal.git")
            (root / "scripts").mkdir()
            (root / "scripts/validate.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
            implementation = commit("implementation including validator")
            rel = "handoffs/T-M1-05-PROVENANCE-DEPLOY-ROOT__codex__to__claude.md"
            handoff = root / rel
            argv = ["run_tests", "--handoff", str(handoff), "--skip-install",
                    "--skip-install-reason", "offline fixture"]

            def mocked_suite(command, **kwargs):
                if command[:3] == [sys.executable, "-m", "unittest"]:
                    return subprocess.CompletedProcess(command, 0, b"Ran 3 tests in 0.01s\n\nOK\n", b"")
                self.assertNotIn("pip", command)
                return real_run(command, **kwargs)

            report = io.StringIO()
            with patch.object(run_tests, "REPO_ROOT", root), patch.object(run_tests, "RESULT_PATH", root / rv.UNITTEST_ARTIFACT_REL), patch.object(run_tests.subprocess, "run", side_effect=mocked_suite), patch.object(sys, "argv", argv), redirect_stdout(report):
                self.assertFalse(handoff.exists())
                self.assertEqual(run_tests.main(), 0)
            artifact, exists = rv.load_unittest_artifact(root)
            self.assertTrue(exists)
            evidence = rv.test_evidence_from_artifact(artifact)
            emitted = report.getvalue().split("### Test Evidence", 1)[1]
            self.assertEqual("### Test Evidence" + emitted, rv.render_test_evidence(evidence) + "\n")
            self.assertEqual(evidence["tests_commit_sha"], implementation)
            handoff.parent.mkdir()
            handoff.write_text("## Repository Verification\n\n" + rv.render_test_evidence(evidence), encoding="utf-8")
            final = commit("record measured evidence and artifact")

            # These values only become known after committing the evidence.
            block = blocks.render_repository_verification_block(
                repo_root=str(root), branch=git("branch", "--show-current"),
                base_sha=implementation, implementation_sha=implementation,
                tests_commit_sha=implementation, final_head_sha=final,
                remote_head_sha=final, git_status_clean_value=True,
                validator_commit_sha=final, test_count=3,
                post_test_files=[rel, rv.UNITTEST_ARTIFACT_REL], test_evidence=evidence)
            handoff.write_text(block, encoding="utf-8")
            commit("annotate closeout SHAs using allowlisted handoff only")

            def verify(text):
                handoff.write_text(text, encoding="utf-8")
                output = io.StringIO()
                with patch.object(verifier, "REPO_ROOT", root), patch.object(sys, "argv", ["verify", rel, "--canonical-repo", str(root)]), redirect_stdout(output), redirect_stderr(output):
                    code = verifier.main()
                return code, output.getvalue()

            code, output = verify(block)
            self.assertEqual(code, 0, output)
            self.assertIn("Status: verified", output)
            self.assertIn("Validator at HEAD: passed", output)
            for key in rv.TEST_EVIDENCE_FIELDS:
                with self.subTest(sealed_field=key):
                    changed = block.replace(f"{key}: {evidence[key]}\n", f"{key}: tampered\n", 1)
                    code, output = verify(changed)
                    self.assertNotEqual(code, 0, output)
                    # Even when early Git checks reject an invalid tests SHA,
                    # the canonical evidence comparison independently rejects it.
                    parsed = rv.parse_verification_block(changed)
                    parsed["expected_repo_identity"] = rv.repository_identity(root)
                    errors, status = rv.validate_test_artifact(
                        artifact, verification=parsed, actual_head_sha=final,
                        artifact_exists=True, is_ancestor=lambda a, b: rv.git_is_ancestor(a, b, str(root)))
                    self.assertEqual(status, "failed")
                    self.assertTrue(any("handoff evidence block hash mismatch" in e for e in errors))
            for key in ("final_head_sha", "remote_head_sha", "validator_commit_sha"):
                with self.subTest(closeout_field=key):
                    code, output = verify(block.replace(f"{key}: {final}", f"{key}: {'0' * 40}"))
                    self.assertNotEqual(code, 0, output)
            self.assertEqual(verify(block)[0], 0)

    def test_canonical_seal_ignores_only_formatting_and_closeout(self):
        evidence = {key: f"value for {key}" for key in rv.TEST_EVIDENCE_FIELDS}
        text = "## Repository Verification\n" + rv.render_test_evidence(evidence)
        self.assertEqual(rv.evidence_block_hash(evidence), rv.evidence_block_hash(text))
        self.assertEqual(rv.evidence_block_hash(text), rv.evidence_block_hash(
            text.replace("\n", "\r\n") + "final_head_sha: " + "f" * 40 + "\n"))
        self.assertNotEqual(rv.evidence_block_hash(evidence), rv.evidence_block_hash({}))

    def test_missing_or_duplicate_evidence_is_rejected(self):
        evidence = rv.test_evidence_from_artifact(_artifact())
        original = "## Repository Verification\n" + rv.render_test_evidence(evidence)
        for text in (
            original.replace("dependency_install_reason: \n", ""),
            original + "test_count: 99\n",
        ):
            with self.subTest(text=text):
                parsed = rv.parse_verification_block(text)
                parsed["expected_repo_identity"] = "identity"
                errors, status = rv.validate_test_artifact(
                    _artifact(), verification=parsed, actual_head_sha=_sha("f"),
                    artifact_exists=True, is_ancestor=lambda a, b: True)
                self.assertEqual(status, "failed", errors)

    def test_supplied_digest_cannot_override_changed_fields(self):
        artifact = _artifact()
        changed = _verification(hostname="edited", evidence_block_sha256=artifact["evidence_block_sha256"])
        errors, status = rv.validate_test_artifact(
            artifact, verification=changed, actual_head_sha=_sha("f"),
            artifact_exists=True, is_ancestor=lambda a, b: True)
        self.assertEqual(status, "failed")
        self.assertTrue(any("handoff evidence block hash mismatch" in e for e in errors))
