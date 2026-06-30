from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_activation import (  # noqa: E402
    build_draft_activation_manifest,
    validate_activation_manifest,
)


class ActivationGateTests(unittest.TestCase):
    def test_draft_manifest_pre_active_status(self) -> None:
        manifest = build_draft_activation_manifest(
            REPO_ROOT,
            activation_id="activation-test-1",
            reviewed_commit_sha="2af82a9e7e812e05059b69653583d1c78dfa43b1",
            base_sha="2af82a9e7e812e05059b69653583d1c78dfa43b1",
            cli_version="0.136.0",
            cli_help_hash="abc123",
            status="awaiting_human_approval",
        )
        self.assertEqual(manifest["status"], "awaiting_human_approval")
        self.assertTrue(manifest["canary_only"])
        self.assertEqual(manifest["maximum_runs"], 1)

    def test_valid_manifest_passes(self) -> None:
        manifest = build_draft_activation_manifest(
            REPO_ROOT,
            activation_id="activation-test-2",
            reviewed_commit_sha="2af82a9e7e812e05059b69653583d1c78dfa43b1",
            base_sha="2af82a9e7e812e05059b69653583d1c78dfa43b1",
            cli_version="0.136.0",
            cli_help_hash="fixture-hash",
        )
        result = validate_activation_manifest(manifest, repo_root=REPO_ROOT)
        self.assertTrue(result.ready_for_review)
        self.assertEqual(result.blockers, [])

    def test_active_status_blocked_in_phase36(self) -> None:
        manifest = build_draft_activation_manifest(
            REPO_ROOT,
            activation_id="activation-test-3",
            reviewed_commit_sha="2af82a9e7e812e05059b69653583d1c78dfa43b1",
            base_sha="2af82a9e7e812e05059b69653583d1c78dfa43b1",
            cli_version="0.136.0",
            cli_help_hash="fixture-hash",
            status="human_approved",
        )
        result = validate_activation_manifest(manifest, repo_root=REPO_ROOT)
        self.assertFalse(result.ready_for_review)
        self.assertTrue(any("not allowed" in b for b in result.blockers))

    def test_config_hash_mismatch_blocks(self) -> None:
        manifest = build_draft_activation_manifest(
            REPO_ROOT,
            activation_id="activation-test-4",
            reviewed_commit_sha="2af82a9e7e812e05059b69653583d1c78dfa43b1",
            base_sha="2af82a9e7e812e05059b69653583d1c78dfa43b1",
            cli_version="0.136.0",
            cli_help_hash="fixture-hash",
        )
        manifest["adapter_config_hash"] = "0" * 64
        result = validate_activation_manifest(manifest, repo_root=REPO_ROOT)
        self.assertFalse(result.ready_for_review)
        self.assertTrue(any("adapter_config_hash" in b for b in result.blockers))


if __name__ == "__main__":
    unittest.main()