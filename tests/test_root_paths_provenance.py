"""Bounded provenance lookup and success-only process caching."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import root_paths


class RootPathsProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / ".git").mkdir()
        root_paths._config_root_sha_cache.clear()
        self.addCleanup(root_paths._config_root_sha_cache.clear)
        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("AGENTIC_OS_CONFIG_ROOT", None)

    def metadata(self):
        return root_paths.root_metadata(self.root)

    @patch("root_paths.run_command")
    def test_timeout_then_success_retries_once(self, run):
        run.side_effect = [subprocess.TimeoutExpired("git", 30),
                           subprocess.CompletedProcess([], 0, "abc123\n", "")]
        result = self.metadata()
        self.assertEqual(result["config_root_git_sha"], "abc123")
        self.assertNotIn("config_root_git_sha_error", result)
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["timeout"], 30)

    @patch("root_paths.run_command")
    def test_persistent_timeout_is_not_cached(self, run):
        run.side_effect = subprocess.TimeoutExpired("git", 30)
        for _ in range(2):
            result = self.metadata()
            self.assertIsNone(result["config_root_git_sha"])
            self.assertEqual(result["config_root_git_sha_error"], "timeout")
        self.assertEqual(run.call_count, 4)

    @patch("root_paths.run_command", side_effect=OSError("missing"))
    def test_git_missing(self, run):
        self.assertEqual(self.metadata()["config_root_git_sha_error"], "git not found")
        self.assertEqual(run.call_count, 1)

    @patch("root_paths.run_command")
    def test_success_cached_per_config_root(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "abc123\n", "")
        self.assertEqual(self.metadata(), self.metadata())
        self.assertEqual(run.call_count, 1)
        other = self.root / "other"
        (other / ".git").mkdir(parents=True)
        root_paths.root_metadata(other)
        self.assertEqual(run.call_count, 2)

    @patch("root_paths.run_command")
    def test_git_error_first_line_and_recovery(self, run):
        run.side_effect = [subprocess.CompletedProcess([], 128, "", "fatal: broken\nextra\n"),
                           subprocess.CompletedProcess([], 0, "abc123", "")]
        self.assertEqual(self.metadata()["config_root_git_sha_error"], "rc=128: fatal: broken")
        self.assertEqual(self.metadata()["config_root_git_sha"], "abc123")

    @patch("root_paths.run_command")
    def test_no_git(self, run):
        (self.root / ".git").rmdir()
        self.assertEqual(self.metadata()["config_root_git_sha_error"], "no .git")
        run.assert_not_called()

    @patch("root_paths.run_command")
    def test_empty_output(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "\n", "")
        self.assertEqual(self.metadata()["config_root_git_sha_error"], "empty git output")
