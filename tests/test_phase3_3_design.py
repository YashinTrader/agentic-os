from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


DESIGN_DOCS = [
    "docs/PHASE_3_3_WORKTREE_ALLOCATOR_DESIGN.md",
    "docs/PHASE_3_3_APPROVAL_AUTHENTICITY_DESIGN.md",
    "docs/PHASE_3_3_SCHEDULING_BOUNDARIES.md",
    "docs/PHASE_3_3_AGENT_ADAPTER_PROMOTION.md",
    "docs/PHASE_3_3_RUNTIME_GOVERNANCE.md",
    "docs/PHASE_3_3_DESIGN_SPEC.md",
    "docs/PHASE_3_3_REVIEW_PACKET.md",
]

ADRS = [
    "decisions/ADR-0020-worktree-allocation-lifecycle.md",
    "decisions/ADR-0021-approval-authenticity-anti-replay.md",
    "decisions/ADR-0022-no-autonomous-execution-default.md",
    "decisions/ADR-0023-real-agent-adapter-promotion.md",
    "decisions/ADR-0024-concurrency-resource-limits.md",
]

SCHEMAS = [
    "schemas/worktree_allocation.schema.json",
    "schemas/adapter_promotion.schema.json",
    "schemas/scheduling_policy.schema.json",
]


class Phase33DesignTests(unittest.TestCase):
    def test_design_docs_exist(self) -> None:
        for rel in DESIGN_DOCS:
            self.assertTrue((REPO_ROOT / rel).exists(), rel)

    def test_adrs_exist_with_sections(self) -> None:
        for rel in ADRS:
            path = REPO_ROOT / rel
            self.assertTrue(path.exists(), rel)
            text = path.read_text(encoding="utf-8")
            for section in ("## Context", "## Decision", "## Consequences"):
                self.assertIn(section, text, f"{rel} missing {section}")

    def test_schemas_parse(self) -> None:
        for rel in SCHEMAS:
            data = json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))
            self.assertIn("type", data)

    def test_scheduling_level_one_in_schema(self) -> None:
        policy = {
            "autonomy_level": 1,
            "global_concurrency_limit": 2,
            "per_agent_concurrency_limit": 1,
            "max_retries": 0,
            "emergency_stop": False,
            "operator_pause": False,
            "prohibited": ["auto_task_pickup"],
        }
        schema = json.loads((REPO_ROOT / "schemas/scheduling_policy.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(policy["autonomy_level"], 1)
        self.assertIn("autonomy_level", schema["properties"])

    def test_real_adapters_remain_execution_false(self) -> None:
        registry = yaml.safe_load((REPO_ROOT / "agents" / "adapter_registry.yaml").read_text(encoding="utf-8"))
        phase37a = (REPO_ROOT / "dispatch" / "codex_activation_gate.py").is_file()
        for adapter in registry["adapters"]:
            if adapter["id"] == "local-python-exec-test":
                self.assertTrue(adapter["supports_execution"])
            elif adapter["id"] == "codex-restricted" and phase37a:
                self.assertTrue(adapter["supports_execution"])
                self.assertEqual(adapter.get("execution_scope"), "canary_only")
            else:
                self.assertFalse(adapter["supports_execution"])

    def test_no_scheduler_execution_module(self) -> None:
        scheduler = REPO_ROOT / "scheduler"
        if scheduler.exists():
            for py in scheduler.rglob("*.py"):
                source = py.read_text(encoding="utf-8")
                self.assertNotIn("subprocess.run", source, str(py))
                self.assertNotIn("execute_dispatch", source, str(py))

    def test_worktree_allocator_is_operator_commanded_only(self) -> None:
        allocator = REPO_ROOT / "dispatch" / "worktree_allocator.py"
        self.assertTrue(allocator.exists())
        source = allocator.read_text(encoding="utf-8")
        self.assertIn("allocate_worktree", source)
        self.assertNotIn("shell=True", source)

    def test_promotion_states_in_schema(self) -> None:
        schema = json.loads((REPO_ROOT / "schemas/adapter_promotion.schema.json").read_text(encoding="utf-8"))
        states = schema["properties"]["state"]["enum"]
        for state in ("planned", "preview_only", "active", "revoked"):
            self.assertIn(state, states)


if __name__ == "__main__":
    unittest.main()