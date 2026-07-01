"""Phase 3.8 — Composer integration design and preview scaffolding tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.composer_adapter import (  # noqa: E402
    load_composer_restricted_adapter,
    validate_composer_preview_contract,
)
from dispatch.execution_route_policy import (  # noqa: E402
    LOCAL_BUILDER_ROUTES,
    ROUTE_CODEX_LOCAL_BUILDER,
    ROUTE_COMPOSER_LOCAL_BUILDER,
    ROUTE_GENERIC_DISPATCH,
    DEDICATED_CANARY_RUNNER_REASON,
    evaluate_execution_route,
    validate_adapter_route_policy,
)
from dispatch.codex_adapter import load_codex_restricted_adapter  # noqa: E402


class ComposerRoutePolicyTests(unittest.TestCase):
    def test_local_builder_routes_include_composer(self) -> None:
        self.assertIn(ROUTE_COMPOSER_LOCAL_BUILDER, LOCAL_BUILDER_ROUTES)
        self.assertIn(ROUTE_CODEX_LOCAL_BUILDER, LOCAL_BUILDER_ROUTES)

    def test_codex_route_unchanged(self) -> None:
        adapter = load_codex_restricted_adapter(REPO_ROOT)
        generic = evaluate_execution_route(adapter, ROUTE_GENERIC_DISPATCH)
        self.assertFalse(generic.allowed)
        self.assertIn(DEDICATED_CANARY_RUNNER_REASON, generic.reasons)
        builder = evaluate_execution_route(adapter, ROUTE_CODEX_LOCAL_BUILDER)
        self.assertTrue(builder.allowed)
        self.assertEqual(validate_adapter_route_policy(adapter), [])

    def test_composer_route_allowed_for_composer_adapter(self) -> None:
        adapter = load_composer_restricted_adapter(REPO_ROOT)
        route = evaluate_execution_route(adapter, ROUTE_COMPOSER_LOCAL_BUILDER)
        self.assertTrue(route.allowed)
        self.assertEqual(validate_adapter_route_policy(adapter), [])

    def test_composer_route_blocked_for_codex(self) -> None:
        adapter = load_codex_restricted_adapter(REPO_ROOT)
        route = evaluate_execution_route(adapter, ROUTE_COMPOSER_LOCAL_BUILDER)
        self.assertFalse(route.allowed)

    def test_codex_route_blocked_for_composer(self) -> None:
        adapter = load_composer_restricted_adapter(REPO_ROOT)
        route = evaluate_execution_route(adapter, ROUTE_CODEX_LOCAL_BUILDER)
        self.assertFalse(route.allowed)

    def test_composer_generic_dispatch_blocked(self) -> None:
        adapter = load_composer_restricted_adapter(REPO_ROOT)
        route = evaluate_execution_route(adapter, ROUTE_GENERIC_DISPATCH)
        self.assertFalse(route.allowed)


class ComposerAdapterContractTests(unittest.TestCase):
    def test_preview_contract_passes(self) -> None:
        adapter = load_composer_restricted_adapter(REPO_ROOT)
        self.assertEqual(validate_composer_preview_contract(adapter), [])
        self.assertFalse(adapter.get("supports_execution"))
        self.assertFalse(adapter.get("secrets_required"))

    def test_denylist_includes_approval_keys(self) -> None:
        adapter = load_composer_restricted_adapter(REPO_ROOT)
        denylist = set(adapter.get("environment_denylist") or [])
        for key in (
            "AGENTIC_OS_HUMAN_APPROVAL_KEY",
            "AGENTIC_OS_REVIEWER_APPROVAL_KEY",
            "GITHUB_TOKEN",
            "SUPABASE_KEY",
        ):
            self.assertIn(key, denylist)


class DashboardAssignmentIndexTests(unittest.TestCase):
    def test_load_composer_assignment_index_pending(self) -> None:
        from dashboard.app import load_composer_assignment_index

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "runtime" / "dispatch" / "assignments" / "inbox"
            inbox.mkdir(parents=True)
            (inbox / "assign-pending.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "assignment_id": "assign-pending",
                        "task_id": "T-PENDING",
                        "adapter_id": "composer-restricted",
                        "assigned_by": "claude",
                        "assigned_to": "composer",
                        "status": "pending",
                        "created_at": "2026-07-01T12:00:00Z",
                        "updated_at": "2026-07-01T12:00:00Z",
                        "execution_route": "composer_local_builder",
                        "task_path": "tasks/active/T-PENDING.yaml",
                        "handoff_rel": "handoffs/T-PENDING__composer__to__claude.md",
                    }
                ),
                encoding="utf-8",
            )
            index, errors = load_composer_assignment_index(root)
            self.assertEqual(errors, [])
            self.assertEqual(len(index["pending_only"]), 1)
            self.assertIn("T-PENDING", index["by_task_id"])


if __name__ == "__main__":
    unittest.main()