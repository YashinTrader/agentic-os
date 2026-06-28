from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.approval_contract import (  # noqa: E402
    DEFAULT_HUMAN_APPROVAL_TTL_MINUTES,
    DEFAULT_REVIEWER_APPROVAL_TTL_MINUTES,
    evaluate_approval_satisfaction,
)
from dispatch.approval_store import (  # noqa: E402
    build_approval_record,
    load_approval_record,
    save_approval_record,
)
from dispatch.freshness import compute_preview_hash  # noqa: E402


def _preview(**overrides) -> dict:
    base = {
        "run_id": "dispatch-20260612T120000Z-test0001",
        "task_id": "T-APPROVE",
        "adapter_id": "local-python-exec-test",
        "command": 'python -c "print(\'agentic-os-executor-test\')"',
        "working_directory": str(REPO_ROOT),
        "scope_paths": ["tasks/"],
        "approval_gate": {"approval_level": "reviewer"},
    }
    base.update(overrides)
    return base


class ApprovalStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        shutil.copytree(REPO_ROOT, self.root, ignore=shutil.ignore_patterns("runtime", ".git"))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_valid_reviewer_record(self) -> None:
        preview = _preview()
        adapter = {"id": "local-python-exec-test", "adapter_type": "cli", "writes_files": False}
        record = build_approval_record(
            preview,
            approval_level="reviewer",
            approved_by="composer",
            approver_type="reviewer",
            adapter=adapter,
        )
        path = save_approval_record(self.root, record)
        self.assertTrue(path.exists())
        loaded = load_approval_record(path)
        self.assertEqual(loaded["approval_id"], record.approval_id)
        self.assertEqual(loaded["preview_hash"], compute_preview_hash(preview, adapter=adapter))

    def test_reviewer_cannot_satisfy_human(self) -> None:
        preview = _preview()
        adapter = {"id": "local-python-exec-test", "adapter_type": "cli", "writes_files": False}
        record = build_approval_record(
            preview,
            approval_level="reviewer",
            approved_by="composer",
            approver_type="reviewer",
            adapter=adapter,
        )
        digest = compute_preview_hash(preview, adapter=adapter)
        result = evaluate_approval_satisfaction(record, digest, "human")
        self.assertFalse(result.satisfied)

    def test_human_satisfies_reviewer(self) -> None:
        preview = _preview()
        adapter = {"id": "local-python-exec-test", "adapter_type": "cli", "writes_files": False}
        record = build_approval_record(
            preview,
            approval_level="human",
            approved_by="operator",
            approver_type="human",
            adapter=adapter,
        )
        digest = compute_preview_hash(preview, adapter=adapter)
        result = evaluate_approval_satisfaction(record, digest, "reviewer")
        self.assertTrue(result.satisfied)

    def test_ttl_defaults(self) -> None:
        self.assertEqual(DEFAULT_HUMAN_APPROVAL_TTL_MINUTES, 30)
        self.assertEqual(DEFAULT_REVIEWER_APPROVAL_TTL_MINUTES, 60)
        preview = _preview()
        adapter = {"id": "local-python-exec-test", "adapter_type": "cli", "writes_files": False}
        human = build_approval_record(
            preview,
            approval_level="human",
            approved_by="op",
            approver_type="human",
            adapter=adapter,
        )
        reviewer = build_approval_record(
            preview,
            approval_level="reviewer",
            approved_by="comp",
            approver_type="reviewer",
            adapter=adapter,
        )
        from datetime import datetime, timezone
        from dispatch.approval_contract import _parse_iso8601

        h_exp = _parse_iso8601(human.expires_at)
        h_app = _parse_iso8601(human.approved_at)
        assert h_exp and h_app
        self.assertEqual(int((h_exp - h_app).total_seconds() / 60), 30)
        r_exp = _parse_iso8601(reviewer.expires_at)
        r_app = _parse_iso8601(reviewer.approved_at)
        assert r_exp and r_app
        self.assertEqual(int((r_exp - r_app).total_seconds() / 60), 60)


if __name__ == "__main__":
    unittest.main()