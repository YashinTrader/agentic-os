import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.memory_extractors import (
    extract_adr_entity,
    extract_event_records,
    extract_repo_records,
    extract_task_entity,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class MemoryExtractorTests(unittest.TestCase):
    def test_extracts_task_entity_with_stable_id_and_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_path = root / "tasks" / "active" / "T-9001.yaml"
            task_path.parent.mkdir(parents=True)
            task_path.write_text(
                "\n".join(
                    [
                        "id: T-9001",
                        "title: Build deterministic extractors",
                        "status: in_progress",
                        "owner: codex",
                        "reviewer: claude",
                        "created_by: codex",
                        "created_at: '2026-05-24T00:00:00Z'",
                        "updated_at: '2026-05-24T01:00:00Z'",
                        "priority: high",
                        "risk_level: medium",
                        "depends_on:",
                        "  - T-0001",
                    ]
                ),
                encoding="utf-8",
            )

            record = extract_task_entity(task_path, root)

        self.assertEqual(record["id"], "memory:entity:task:T-9001")
        self.assertEqual(record["type"], "entity")
        self.assertEqual(record["namespace"], "system/derived")
        self.assertEqual(record["entity_type"], "task")
        self.assertEqual(record["canonical_id"], "T-9001")
        self.assertEqual(record["source"]["path"], "tasks/active/T-9001.yaml")
        self.assertEqual(record["refs"]["tasks"], ["T-9001"])
        self.assertEqual(record["metadata"]["task_status"], "in_progress")
        self.assertEqual(record["relations"], [{"type": "depends_on", "target": "T-0001"}])

    def test_extracts_adr_entity_status_from_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adr_path = root / "decisions" / "ADR-0099-example.md"
            adr_path.parent.mkdir(parents=True)
            adr_path.write_text(
                "\n".join(
                    [
                        "# ADR-0099: Example Decision",
                        "",
                        "- Status: **Accepted**",
                        "- Date: 2026-05-24",
                        "- Deciders: codex, claude",
                    ]
                ),
                encoding="utf-8",
            )

            record = extract_adr_entity(adr_path, root)

        self.assertEqual(record["id"], "memory:entity:adr:ADR-0099")
        self.assertEqual(record["canonical_id"], "ADR-0099")
        self.assertEqual(record["name"], "Example Decision")
        self.assertEqual(record["metadata"]["adr_status"], "accepted")
        self.assertEqual(record["source"]["path"], "decisions/ADR-0099-example.md")
        self.assertEqual(record["refs"]["adrs"], ["ADR-0099"])

    def test_extracts_episodic_events_and_handles_v1_log_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "logs" / "agent-events.jsonl"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "ts": "2026-05-24T00:00:00Z",
                                "agent": "codex",
                                "task": "T-9001",
                                "event": "started",
                                "detail": "started legacy task",
                            }
                        ),
                        json.dumps(
                            {
                                "ts": "2026-05-24T00:01:00Z",
                                "agent": "claude",
                                "task_id": "T-9001",
                                "type": "reviewed",
                                "detail": "reviewed task",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            first = extract_event_records(log_path, root)
            second = extract_event_records(log_path, root)

        self.assertEqual([record["id"] for record in first], [record["id"] for record in second])
        self.assertEqual(first[0]["type"], "episodic_event")
        self.assertEqual(first[0]["event_type"], "started")
        self.assertEqual(first[0]["task_id"], "T-9001")
        self.assertEqual(first[0]["event_ref"], "logs/agent-events.jsonl:1")
        self.assertEqual(first[1]["event_type"], "reviewed")
        self.assertEqual(first[1]["actor"], "claude")

    def test_extract_repo_records_is_deterministic(self) -> None:
        first = extract_repo_records(REPO_ROOT)
        second = extract_repo_records(REPO_ROOT)

        self.assertEqual([record["id"] for record in first], [record["id"] for record in second])
        self.assertTrue(any(record["id"] == "memory:entity:task:T-0023" for record in first))
        self.assertTrue(any(record["id"] == "memory:entity:adr:ADR-0007" for record in first))
        self.assertTrue(any(record["type"] == "episodic_event" for record in first))

    def test_cli_outputs_jsonl_records(self) -> None:
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "memory_extractors.py"), "--jsonl"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )

        first_line = result.stdout.splitlines()[0]
        payload = json.loads(first_line)
        self.assertIn("id", payload)
        self.assertIn(payload["type"], {"entity", "episodic_event"})


if __name__ == "__main__":
    unittest.main()
