from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from scripts.agentic_os_memory import CONTRACT_VERSION, FixtureMemoryBackend, MemoryAdapter


REPO_ROOT = Path(__file__).resolve().parents[1]


class MemoryAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = MemoryAdapter(FixtureMemoryBackend())

    def assert_tool_error(self, result: dict, code: str) -> None:
        self.assertTrue(result["isError"])
        error = result["structuredContent"]
        self.assertEqual(error["code"], code)
        self.assertIn("message", error)
        self.assertIn("retryable", error)

    def test_tool_list_contains_read_tools_only(self) -> None:
        names = [tool["name"] for tool in self.adapter.list_tools()]

        self.assertEqual(
            names,
            [
                "memory.search",
                "memory.get",
                "memory.list_entities",
                "memory.timeline",
                "memory.graph_neighbors",
            ],
        )
        self.assertNotIn("memory.write", names)
        self.assertNotIn("memory.retract", names)
        self.assertNotIn("memory.mark_disputed", names)

    def test_empty_search_returns_contract_version_and_empty_results(self) -> None:
        result = self.adapter.call_tool("memory.search", {"query": "ADR-0007"})

        self.assertFalse(result.get("isError", False))
        payload = result["structuredContent"]
        self.assertEqual(payload["contract_version"], CONTRACT_VERSION)
        self.assertEqual(payload["results"], [])
        self.assertIsNone(payload["next_cursor"])

    def test_get_missing_record_returns_not_found_error(self) -> None:
        result = self.adapter.call_tool("memory.get", {"id": "memory:missing"})

        self.assert_tool_error(result, "NOT_FOUND")

    def test_search_rejects_empty_query(self) -> None:
        result = self.adapter.call_tool("memory.search", {"query": "   "})

        self.assert_tool_error(result, "INVALID_ARGUMENT")

    def test_search_rejects_forbidden_private_namespace(self) -> None:
        result = self.adapter.call_tool(
            "memory.search",
            {"query": "draft", "namespaces": ["agent/claude"], "include_private": True},
            identity={"agent_id": "codex", "role": "reader"},
        )

        self.assert_tool_error(result, "FORBIDDEN_NAMESPACE")

    def test_fixture_backend_success_paths(self) -> None:
        backend = FixtureMemoryBackend.with_records(
            records=[
                {
                    "id": "memory:entity:adr:ADR-0007",
                    "type": "entity",
                    "namespace": "shared",
                    "content": "ADR-0007 selected Cognee for memory architecture.",
                    "source": {"kind": "adr", "path": "decisions/ADR-0007-memory-architecture.md"},
                    "created_at": "2026-05-24T00:00:00Z",
                    "created_by": "librarian",
                    "confidence": 1.0,
                    "refs": {"adrs": ["ADR-0007"]},
                    "visibility": "shared",
                    "status": "active",
                    "ttl": None,
                    "metadata": {},
                    "entity_type": "adr",
                    "canonical_id": "ADR-0007",
                    "name": "Memory architecture for Agentic OS",
                    "aliases": [],
                    "relations": [],
                }
            ],
            events=[
                {
                    "id": "memory:episodic:1",
                    "event_type": "decision_recorded",
                    "actor": "codex",
                    "occurred_at": "2026-05-24T00:00:00Z",
                    "event_ref": "logs/agent-events.jsonl:1",
                    "task_id": "T-0019",
                    "content": "ADR-0007 was accepted.",
                    "entity_ids": ["ADR-0007"],
                }
            ],
            edges=[
                {
                    "from": "memory:entity:task:T-0022",
                    "to": "memory:entity:adr:ADR-0009",
                    "type": "depends_on",
                },
                {
                    "from": "memory:entity:adr:ADR-0009",
                    "to": "memory:entity:task:T-0021",
                    "type": "derived_from",
                }
            ],
        )
        adapter = MemoryAdapter(backend)

        search = adapter.call_tool("memory.search", {"query": "Cognee"})
        self.assertEqual(search["structuredContent"]["results"][0]["id"], "memory:entity:adr:ADR-0007")

        get = adapter.call_tool("memory.get", {"id": "memory:entity:adr:ADR-0007"})
        self.assertEqual(get["structuredContent"]["record"]["canonical_id"], "ADR-0007")

        entities = adapter.call_tool("memory.list_entities", {"entity_type": "adr"})
        self.assertEqual(entities["structuredContent"]["entities"][0]["canonical_id"], "ADR-0007")

        timeline = adapter.call_tool("memory.timeline", {"entity_id": "ADR-0007"})
        self.assertEqual(timeline["structuredContent"]["events"][0]["event_type"], "decision_recorded")

        neighbors = adapter.call_tool("memory.graph_neighbors", {"id": "memory:entity:task:T-0022"})
        self.assertEqual(neighbors["structuredContent"]["edges"][0]["type"], "depends_on")

        depth_two = adapter.call_tool("memory.graph_neighbors", {"id": "memory:entity:task:T-0022", "depth": 2})
        depth_two_ids = {node["id"] for node in depth_two["structuredContent"]["nodes"]}
        self.assertIn("memory:entity:task:T-0021", depth_two_ids)

    def test_entrypoint_lists_read_tools(self) -> None:
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "agentic-os-memory"), "--list-tools"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )

        payload = json.loads(result.stdout)
        names = [tool["name"] for tool in payload["tools"]]
        self.assertIn("memory.search", names)
        self.assertNotIn("memory.write", names)


if __name__ == "__main__":
    unittest.main()
