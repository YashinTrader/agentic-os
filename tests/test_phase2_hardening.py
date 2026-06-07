from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from orchestrator.graph import run_orchestration  # noqa: E402
from protocol.event_types import ALLOWED_EVENT_TYPES  # noqa: E402
from scripts.orchestrate_task import resolve_output_dir  # noqa: E402
from scripts.validate import validate_logs  # noqa: E402


class Phase2HardeningTests(unittest.TestCase):
    def test_valid_output_dir_under_runtime_passes(self) -> None:
        root = REPO_ROOT.resolve()
        resolved = resolve_output_dir(root, "runtime/orchestrator/runs")
        self.assertTrue(resolved.startswith(str(root)))
        self.assertIn("orchestrator", resolved)

    def test_path_traversal_output_dir_fails(self) -> None:
        root = REPO_ROOT.resolve()
        with self.assertRaises(ValueError) as ctx:
            resolve_output_dir(root, "runtime/../../outside")
        self.assertIn("traversal", str(ctx.exception).lower())

    def test_absolute_output_dir_outside_repo_fails(self) -> None:
        root = REPO_ROOT.resolve()
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp).resolve()
            with self.assertRaises(ValueError) as ctx:
                resolve_output_dir(root, str(outside))
            self.assertIn("inside repository", str(ctx.exception))

    def test_missing_task_does_not_generate_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tasks" / "active").mkdir(parents=True)
            (root / "runtime" / "orchestrator").mkdir(parents=True)
            state = run_orchestration(
                root,
                "tasks/active/MISSING-TASK.yaml",
                dry_run=False,
                no_log=True,
            )
            self.assertTrue(state.errors)
            self.assertEqual(state.next_action, "fix_task_input")
            self.assertFalse(state.plan_path)
            latest = root / "runtime" / "orchestrator" / "latest_state.json"
            self.assertTrue(latest.exists())
            payload = json.loads(latest.read_text(encoding="utf-8"))
            self.assertTrue(payload.get("errors"))
            self.assertIsNone(payload.get("plan_path"))
            self.assertFalse((root / "runtime" / "orchestrator" / "latest_plan.json").exists())

    def test_invalid_yaml_does_not_generate_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "tasks" / "active"
            task_dir.mkdir(parents=True)
            (root / "runtime" / "orchestrator").mkdir(parents=True)
            bad = task_dir / "T-BAD.yaml"
            bad.write_text("id: [not: valid: yaml", encoding="utf-8")
            state = run_orchestration(root, "tasks/active/T-BAD.yaml", dry_run=False, no_log=True)
            self.assertTrue(state.errors)
            self.assertEqual(state.next_action, "fix_task_input")
            self.assertFalse(state.plan_path)

    def test_phase2_event_types_documented(self) -> None:
        for event_type in (
            "discovery_completed",
            "registry_updated",
            "vault_sync_planned",
            "vault_sync_completed",
            "orchestration_planned",
            "validation_passed",
            "review_packet_created",
        ):
            self.assertIn(event_type, ALLOWED_EVENT_TYPES)

    def test_validator_rejects_undocumented_event_type(self) -> None:
        errors: list[str] = []
        warnings: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "logs").mkdir()
            log = root / "logs" / "agent-events.jsonl"
            log.write_text(
                json.dumps(
                    {
                        "ts": "2026-06-07T12:00:00Z",
                        "agent": "test",
                        "type": "totally_made_up_event",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            original_root = REPO_ROOT
            try:
                import scripts.validate as validate_mod

                validate_mod.ROOT = root
                validate_logs(errors, warnings)
            finally:
                validate_mod.ROOT = original_root
        self.assertTrue(any("unknown event type" in e for e in errors))

    def test_dashboard_loader_handles_orchestrator_error_state(self) -> None:
        from dashboard.app import load_orchestrator_latest

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = root / "runtime" / "orchestrator"
            orch.mkdir(parents=True)
            (orch / "latest_state.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-test",
                        "task_id": "T-ERR",
                        "errors": ["load_task failed: task file not found"],
                        "next_action": "fix_task_input",
                        "plan_path": None,
                    }
                ),
                encoding="utf-8",
            )
            plan, state, errors = load_orchestrator_latest(root)
            self.assertIsNone(plan)
            self.assertIsNotNone(state)
            self.assertEqual(state.get("next_action"), "fix_task_input")
            self.assertTrue(state.get("errors"))

    def test_review_packet_files_exist_with_sections(self) -> None:
        required = {
            REPO_ROOT / "docs" / "PHASE_2_REVIEW_PACKET.md": [
                "## A. Phase 2.0",
                "## G. Claude review checklist",
            ],
            REPO_ROOT / "docs" / "PHASE_2_HARDENING_REPORT.md": [
                "## Known limitations fixed",
                "## Phase 2 readiness for Claude review",
            ],
            REPO_ROOT / "docs" / "PHASE_3_READINESS_CRITERIA.md": [
                "## A. Execution gates",
                "## E. Rollback gates",
            ],
        }
        for path, sections in required.items():
            self.assertTrue(path.exists(), f"missing {path}")
            text = path.read_text(encoding="utf-8")
            for section in sections:
                self.assertIn(section, text, f"{path.name} missing {section}")

    def test_hardening_adrs_exist_with_sections(self) -> None:
        for name in (
            "ADR-0010-phase-2-runtime-registries.md",
            "ADR-0011-langgraph-planning-only-orchestrator.md",
            "ADR-0012-phase-3-agent-dispatch-gates.md",
        ):
            path = REPO_ROOT / "decisions" / name
            self.assertTrue(path.exists(), name)
            text = path.read_text(encoding="utf-8")
            self.assertIn("## Context", text)
            self.assertIn("## Decision", text)
            self.assertIn("## Consequences", text)

    def test_append_log_accepts_orchestration_planned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "append_log.py"),
                    "--root",
                    str(root),
                    "--agent",
                    "orchestrator",
                    "--type",
                    "orchestration_planned",
                    "--task-id",
                    "T-TEST",
                    "--detail",
                    "test event",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()