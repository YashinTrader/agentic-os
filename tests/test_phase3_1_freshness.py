from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.approval_contract import ApprovalRecord  # noqa: E402
from dispatch.freshness import (  # noqa: E402
    compute_preview_hash,
    is_approval_fresh,
    is_preview_stale,
)
from dispatch.preview import (  # noqa: E402
    load_adapter_registry,
    parse_key_value_token,
    validate_command_allowlist,
    validate_key_value_forbidden_args,
)


def _preview(**overrides) -> dict:
    base = {
        "command": "composer agent run --dry-run --task-id T-1",
        "working_directory": "/repo",
        "scope_paths": ["tasks/", "handoffs/"],
        "adapter_id": "composer-cli-preview",
        "task_id": "T-1",
        "approval_gate": {"approval_level": "reviewer"},
        "risk_gate": {"risk_level": "low"},
    }
    base.update(overrides)
    return base


def _future_iso(minutes: int = 60) -> str:
    dt = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _past_iso(minutes: int = 60) -> str:
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class FreshnessTests(unittest.TestCase):
    def test_module_has_no_subprocess(self) -> None:
        source = (REPO_ROOT / "dispatch" / "freshness.py").read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("subprocess.", source)

    def test_same_preview_same_hash(self) -> None:
        p = _preview()
        self.assertEqual(compute_preview_hash(p), compute_preview_hash(p))

    def test_changed_command_changes_hash(self) -> None:
        h1 = compute_preview_hash(_preview())
        h2 = compute_preview_hash(_preview(command="composer agent run --dry-run --task-id T-2"))
        self.assertNotEqual(h1, h2)

    def test_changed_cwd_changes_hash(self) -> None:
        h1 = compute_preview_hash(_preview())
        h2 = compute_preview_hash(_preview(working_directory="/other"))
        self.assertNotEqual(h1, h2)

    def test_changed_scope_path_changes_hash(self) -> None:
        h1 = compute_preview_hash(_preview())
        h2 = compute_preview_hash(_preview(scope_paths=["tasks/", "scripts/"]))
        self.assertNotEqual(h1, h2)

    def test_mismatched_preview_hash_stale_approval(self) -> None:
        preview = _preview()
        digest = compute_preview_hash(preview)
        record = ApprovalRecord(
            approval_id="apr-1",
            task_id="T-1",
            run_id="dispatch-1",
            preview_hash="0" * 64,
            adapter_id="composer-cli-preview",
            approval_level="reviewer",
            approved_by="claude",
            approver_type="reviewer",
            approved_at="2026-06-11T12:00:00Z",
            expires_at=_future_iso(),
            scope="test",
            allowed_command_hash=digest,
            allowed_cwd="/repo",
            allowed_scope_paths=("tasks/",),
        )
        self.assertFalse(is_approval_fresh(digest, record))

    def test_expired_approval_not_fresh(self) -> None:
        preview = _preview()
        digest = compute_preview_hash(preview)
        record = ApprovalRecord(
            approval_id="apr-1",
            task_id="T-1",
            run_id="dispatch-1",
            preview_hash=digest,
            adapter_id="composer-cli-preview",
            approval_level="reviewer",
            approved_by="claude",
            approver_type="reviewer",
            approved_at="2026-06-11T12:00:00Z",
            expires_at=_past_iso(),
            scope="test",
            allowed_command_hash=digest,
            allowed_cwd="/repo",
            allowed_scope_paths=("tasks/",),
        )
        self.assertFalse(is_approval_fresh(digest, record))

    def test_matching_hash_fresh_approval(self) -> None:
        preview = _preview()
        digest = compute_preview_hash(preview)
        record = ApprovalRecord(
            approval_id="apr-1",
            task_id="T-1",
            run_id="dispatch-1",
            preview_hash=digest,
            adapter_id="composer-cli-preview",
            approval_level="reviewer",
            approved_by="claude",
            approver_type="reviewer",
            approved_at="2026-06-11T12:00:00Z",
            expires_at=_future_iso(),
            scope="test",
            allowed_command_hash=digest,
            allowed_cwd="/repo",
            allowed_scope_paths=("tasks/",),
        )
        self.assertTrue(is_approval_fresh(digest, record))

    def test_is_preview_stale_on_context_drift(self) -> None:
        preview = _preview()
        baseline = compute_preview_hash(preview)
        drifted_task = {"id": "T-2", "risk_level": "high"}
        self.assertTrue(
            is_preview_stale(preview, current_task=drifted_task, baseline_hash=baseline)
        )

    def test_key_value_forbidden_key_detection(self) -> None:
        registry = load_adapter_registry(REPO_ROOT)
        adapter = next(a for a in registry["adapters"] if a["id"] == "composer-cli-preview")
        cmd = "composer agent run --dry-run --execute=true --task-id T-1"
        errors = validate_command_allowlist(adapter, cmd)
        self.assertTrue(any("forbidden argument key" in e for e in errors))

    def test_quoted_key_value_forbidden(self) -> None:
        registry = load_adapter_registry(REPO_ROOT)
        adapter = next(a for a in registry["adapters"] if a["id"] == "composer-cli-preview")
        cmd = 'composer run --dry-run "--execute=false" --task-id T-1'
        errors = validate_key_value_forbidden_args(adapter, cmd)
        self.assertTrue(any("forbidden argument key" in e for e in errors))

    def test_parse_key_value_token(self) -> None:
        parsed = parse_key_value_token("--execute=true")
        self.assertEqual(parsed, ("--execute", "true"))

    def test_execution_events_not_in_allowed_yet(self) -> None:
        from protocol.event_types import ALLOWED_EVENT_TYPES, PHASE_3_2_EXECUTION_EVENT_TYPES

        for event in PHASE_3_2_EXECUTION_EVENT_TYPES:
            self.assertNotIn(
                event,
                ALLOWED_EVENT_TYPES,
                f"{event} must stay reserved until Phase 3.2 emitter exists",
            )


if __name__ == "__main__":
    unittest.main()