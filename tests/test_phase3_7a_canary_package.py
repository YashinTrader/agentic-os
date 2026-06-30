from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_activation import activation_bundle_dir  # noqa: E402
from dispatch.codex_canary_contract import compute_canary_contract_hash  # noqa: E402


class Phase37aCanaryPackageTests(unittest.TestCase):
    REVIEWED = "d9f203c39c3a85613ef4c7f76e110e3f4734d9c1"

    def test_prepare_writes_bundle_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            activation = "activation-pkg-test"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "prepare_codex_canary.py"),
                    "--root",
                    str(REPO_ROOT),
                    "--activation",
                    activation,
                    "--run-id",
                    "run-pkg-001",
                    "--reviewed-sha",
                    self.REVIEWED,
                    "--cli-help-hash",
                    "fixture",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            bundle = activation_bundle_dir(REPO_ROOT, activation)
            self.assertTrue((bundle / "activation_manifest.json").is_file())
            self.assertTrue((bundle / "human_approval_request.json").is_file())
            self.assertTrue((bundle / "preflight.json").is_file())
            preflight = json.loads((bundle / "preflight.json").read_text(encoding="utf-8"))
            self.assertFalse(preflight["codex_subprocess_invoked"])
            self.assertFalse(preflight["worktree_allocated"])

    def test_canary_contract_hash_deterministic(self) -> None:
        h1 = compute_canary_contract_hash(reviewed_commit_sha=self.REVIEWED, cli_version="0.136.0")
        h2 = compute_canary_contract_hash(reviewed_commit_sha=self.REVIEWED, cli_version="0.136.0")
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)


if __name__ == "__main__":
    unittest.main()