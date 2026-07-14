from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import yaml

from dispatch.agent_wake import request_agent_wake
from dispatch.assignment_channel import claim_assignment, complete_assignment, read_assignment, resolve_assignment, write_assignment
from dispatch.orchestrator_pokes import list_orchestrator_pokes, write_orchestrator_poke
from scripts.watch_assignments import process_one


class WakePokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        agents = self.root / "agents"
        agents.mkdir()
        (agents / "adapter_registry.yaml").write_text("adapters: []\n", encoding="utf-8")
        for adapter, mechanism in (("composer-restricted", "assignment_watcher"), ("codex-restricted", "codex_local_builder")):
            (agents / f"{adapter.replace('-', '_')}_adapter.yaml").write_text(
                yaml.safe_dump({"wake": {"enabled": True, "mechanism": mechanism, "command_or_path": "worker.py"}}), encoding="utf-8"
            )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _assignment(self, *, assigned_to: str = "composer", wake: bool = True) -> str:
        path, errors = write_assignment(
            self.root, task_id="T-WAKE", title="Wake", goal="Wake", assigned_to=assigned_to,
            assignment_id=f"assign-{assigned_to}", task_path="tasks/active/T-WAKE.yaml", wake=wake,
        )
        self.assertEqual(errors, [])
        assert path is not None
        return path.stem

    def test_composer_wake_queue_is_consumed_by_watcher_and_claims(self) -> None:
        assignment_id = self._assignment()
        record, _ = read_assignment(self.root, assignment_id)
        assert record is not None
        self.assertTrue(record.wake_delivered)
        self.assertEqual(record.wake_state, "wake_delivered")
        report = process_one(self.root, "composer")
        self.assertEqual(report["status"], "claimed")
        claimed, _ = read_assignment(self.root, assignment_id)
        self.assertEqual(claimed.status, "claimed")

    def test_non_claude_wake_is_rejected(self) -> None:
        path, errors = write_assignment(
            self.root, task_id="T-WAKE", assigned_by="other-orchestrator",
            assigned_to="composer", assignment_id="assign-denied", wake=True,
        )
        self.assertIsNone(path)
        self.assertIn("only claude", errors[0])

    def test_codex_wake_reuses_worker_eligibility(self) -> None:
        task_path = self.root / "tasks" / "active" / "T-WAKE.yaml"
        task_path.parent.mkdir(parents=True)
        task_path.write_text("id: T-WAKE\n", encoding="utf-8")
        with patch("dispatch.codex_local_builder_gate.evaluate_worker_task_eligibility", return_value=(True, "eligible")) as gate:
            assignment_id = self._assignment(assigned_to="codex")
        record, _ = read_assignment(self.root, assignment_id)
        self.assertTrue(record.wake_delivered)
        self.assertEqual(record.wake_state, "wake_delivered")
        gate.assert_called_once()

    def test_unknown_mechanism_is_pending_not_error(self) -> None:
        (self.root / "agents" / "composer_restricted_adapter.yaml").write_text(
            yaml.safe_dump({"wake": {"enabled": True, "mechanism": "future_hook", "command_or_path": "x"}}), encoding="utf-8"
        )
        outcome = request_agent_wake(
            self.root, assignment_id="a", task_id="T", agent_id="composer",
            adapter_id="composer-restricted", task_path="tasks/active/T.yaml", requested_by="claude",
        )
        self.assertEqual(outcome.state, "pending_wake")
        self.assertFalse(outcome.delivered)

    def test_poke_topology_and_drain(self) -> None:
        denied, errors = write_orchestrator_poke(
            self.root, source="composer", target="codex", assignment_id="a", task_id="T", event="done"
        )
        self.assertIsNone(denied)
        self.assertTrue(errors)
        written, errors = write_orchestrator_poke(
            self.root, source="composer", assignment_id="a", task_id="T", event="done"
        )
        self.assertEqual(errors, [])
        self.assertIsNotNone(written)
        records, errors = list_orchestrator_pokes(self.root, drain=True)
        self.assertEqual(errors, [])
        self.assertEqual(len(records), 1)
        remaining, _ = list_orchestrator_pokes(self.root)
        self.assertEqual(remaining, [])

    def test_complete_and_resolution_emit_pokes(self) -> None:
        assignment_id = self._assignment(wake=False)
        claim_assignment(self.root, assignment_id, sync_task_yaml=False)
        complete_assignment(self.root, assignment_id, sync_task_yaml=False)
        pokes, _ = list_orchestrator_pokes(self.root)
        self.assertEqual([p["event"] for p in pokes], ["assignment_completed"])
        resolve_assignment(self.root, assignment_id, resolution="accepted", sync_task_yaml=False)
        pokes, _ = list_orchestrator_pokes(self.root)
        self.assertEqual({p["event"] for p in pokes}, {"assignment_completed", "assignment_accepted"})


if __name__ == "__main__":
    unittest.main()
