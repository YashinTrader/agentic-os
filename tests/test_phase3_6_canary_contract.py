from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_canary_contract import (  # noqa: E402
    CANARY_FIXED_SENTENCE,
    build_canary_contract,
    build_canary_file_content,
    compute_canary_contract_hash,
    expected_canary_relative_path,
    validate_canary_file_changes,
    validate_canary_path,
)


class CanaryContractTests(unittest.TestCase):
    def test_contract_hash_stable(self) -> None:
        self.assertEqual(compute_canary_contract_hash(), build_canary_contract().contract_hash)

    def test_allowed_path_pattern(self) -> None:
        rel = expected_canary_relative_path("run-001")
        self.assertEqual(validate_canary_path(rel), [])
        self.assertTrue(validate_canary_path("src/evil.py"))

    def test_exactly_one_file_added(self) -> None:
        rel = expected_canary_relative_path("run-002")
        ok = validate_canary_file_changes(added_paths=[rel], modified_paths=[], deleted_paths=[])
        self.assertTrue(ok.allowed)
        bad = validate_canary_file_changes(added_paths=[rel, rel], modified_paths=[], deleted_paths=[])
        self.assertFalse(bad.allowed)

    def test_forbids_modifications_and_deletions(self) -> None:
        rel = expected_canary_relative_path("run-003")
        mod = validate_canary_file_changes(added_paths=[rel], modified_paths=["README.md"], deleted_paths=[])
        self.assertFalse(mod.allowed)
        deleted = validate_canary_file_changes(added_paths=[rel], modified_paths=[], deleted_paths=["README.md"])
        self.assertFalse(deleted.allowed)

    def test_documentation_only_content(self) -> None:
        content = build_canary_file_content(run_id="run-004")
        self.assertIn(CANARY_FIXED_SENTENCE, content)
        self.assertNotIn("import ", content)
        self.assertNotIn("api_key", content.lower())


if __name__ == "__main__":
    unittest.main()