import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.memory_librarian import (
    AUDIT_EVENT_TYPE,
    append_audit_event,
    run_librarian,
    source_refs,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def candidate(record_id: str, *, content: str = "Task fact", confidence: float = 1.0) -> dict:
    return {
        "id": record_id,
        "type": "entity",
        "namespace": "system/derived",
        "content": content,
        "source": {"kind": "task", "path": "tasks/done/T-9001.yaml", "line": 1, "id": "T-9001"},
        "created_at": "2026-05-24T00:00:00Z",
        "created_by": "memory_extractor",
        "confidence": confidence,
        "refs": {
            "tasks": ["T-9001"],
            "adrs": [],
            "events": [],
            "files": ["tasks/done/T-9001.yaml"],
            "commits": [],
            "handoffs": [],
        },
        "visibility": "shared",
        "status": "active",
        "ttl": None,
        "metadata": {},
        "entity_type": "task",
        "canonical_id": "T-9001",
        "name": "Fixture task",
        "aliases": [],
        "relations": [],
    }


class MemoryLibrarianTests(unittest.TestCase):
    def test_audit_event_type_is_allowed_by_adr_0004(self) -> None:
        adr_text = (REPO_ROOT / "decisions" / "ADR-0004-event-vocabulary.md").read_text(encoding="utf-8")

        self.assertIn(f"`{AUDIT_EVENT_TYPE}`", adr_text)

    def test_source_refs_are_stable_and_repo_relative(self) -> None:
        refs = source_refs(candidate("memory:entity:task:T-9001"))

        self.assertEqual(refs[0], "tasks/done/T-9001.yaml:1")
        self.assertIn("tasks/done/T-9001.yaml", refs)

    def test_dry_run_accepts_cited_high_confidence_candidate_with_undo(self) -> None:
        result = run_librarian([candidate("memory:entity:task:T-9001")], run_ts="2026-05-24T00:00:00Z")

        self.assertEqual(result["summary"]["candidates"], 1)
        self.assertEqual(result["summary"]["writes"], 1)
        self.assertFalse(result["summary"]["shared_writes_enabled"])
        decision = result["decisions"][0]
        self.assertEqual(decision["action"], "would_write")
        self.assertEqual(decision["undo"]["operation"], "create")
        self.assertEqual(decision["undo"]["previous_record"], None)
        self.assertEqual(decision["undo"]["new_record"]["id"], "memory:entity:task:T-9001")

    def test_rejects_uncited_and_low_confidence_candidates(self) -> None:
        uncited = candidate("memory:entity:task:T-uncited")
        uncited["source"] = {}
        low_confidence = candidate("memory:entity:task:T-low", confidence=0.5)

        result = run_librarian([uncited, low_confidence], run_ts="2026-05-24T00:00:00Z")

        self.assertEqual(result["summary"]["writes"], 0)
        self.assertEqual(result["summary"]["skips"], 2)
        reasons = [decision["reason"] for decision in result["decisions"]]
        self.assertEqual(reasons, ["uncited", "low_confidence"])

    def test_detects_conflicting_records_with_same_id(self) -> None:
        first = candidate("memory:entity:task:T-9001", content="Original")
        second = candidate("memory:entity:task:T-9001", content="Changed")

        result = run_librarian([first, second], run_ts="2026-05-24T00:00:00Z")

        self.assertEqual(result["summary"]["writes"], 1)
        self.assertEqual(result["summary"]["conflicts"], 1)
        self.assertEqual(result["decisions"][1]["action"], "conflict")
        self.assertEqual(result["decisions"][1]["existing_record"]["content"], "Original")
        self.assertEqual(result["decisions"][1]["record"]["content"], "Changed")

    def test_skips_exact_duplicates_idempotently(self) -> None:
        record = candidate("memory:entity:task:T-9001")

        first = run_librarian([record, dict(record)], run_ts="2026-05-24T00:00:00Z")
        second = run_librarian([record, dict(record)], run_ts="2026-05-24T00:00:00Z")

        self.assertEqual(first["summary"], second["summary"])
        self.assertEqual([decision["action"] for decision in first["decisions"]], ["would_write", "skip"])
        self.assertEqual(first["decisions"][1]["reason"], "duplicate")
        self.assertEqual(first["summary"]["writes"], 1)
        self.assertEqual(first["summary"]["skips"], 1)

    def test_skips_persona_records_before_write_planning(self) -> None:
        record = candidate("memory:persona:agent:codex")
        record["type"] = "persona"
        record["entity_type"] = "agent"
        record["canonical_id"] = "codex"

        result = run_librarian([record], run_ts="2026-05-24T00:00:00Z")

        self.assertEqual(result["summary"]["writes"], 0)
        self.assertEqual(result["summary"]["skips"], 1)
        self.assertEqual(result["decisions"][0]["action"], "skip")
        self.assertEqual(result["decisions"][0]["reason"], "persona_record")
        self.assertNotIn("undo", result["decisions"][0])

    def test_skips_private_namespace_records_before_write_planning(self) -> None:
        record = candidate("memory:entity:agent-private:T-9001")
        record["namespace"] = "agent/codex"

        result = run_librarian([record], run_ts="2026-05-24T00:00:00Z")

        self.assertEqual(result["summary"]["writes"], 0)
        self.assertEqual(result["summary"]["skips"], 1)
        self.assertEqual(result["decisions"][0]["action"], "skip")
        self.assertEqual(result["decisions"][0]["reason"], "private_namespace")
        self.assertNotIn("undo", result["decisions"][0])

    def test_circuit_breaker_opens_after_more_than_three_bad_candidates(self) -> None:
        records = []
        for index in range(5):
            record = candidate(f"memory:entity:task:T-bad-{index}", confidence=0.1)
            records.append(record)

        result = run_librarian(records, run_ts="2026-05-24T00:00:00Z", circuit_breaker_threshold=3)

        self.assertTrue(result["summary"]["circuit_breaker"])
        self.assertEqual(result["summary"]["skips"], 5)
        self.assertEqual(result["decisions"][-1]["reason"], "circuit_breaker_open")

    def test_append_audit_event_records_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_librarian([candidate("memory:entity:task:T-9001")], run_ts="2026-05-24T00:00:00Z")
            append_audit_event(root, result["summary"], task_id="T-0025", ts="2026-05-24T00:01:00Z")
            event = json.loads((root / "logs" / "agent-events.jsonl").read_text(encoding="utf-8"))

        self.assertEqual(event["type"], "note")
        self.assertEqual(event["task_id"], "T-0025")
        self.assertEqual(event["counts"]["candidates"], 1)
        self.assertEqual(event["counts"]["writes"], 1)

    def test_cli_runs_over_fixture_jsonl(self) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(json.dumps(candidate("memory:entity:task:T-9001")) + "\n")
            fixture_path = Path(handle.name)

        self.addCleanup(fixture_path.unlink)
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "memory_librarian.py"),
                "--input-jsonl",
                str(fixture_path),
                "--jsonl",
                "--run-ts",
                "2026-05-24T00:00:00Z",
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )

        lines = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(lines[0]["kind"], "candidate_decision")
        self.assertEqual(lines[-1]["kind"], "run_summary")
        self.assertEqual(lines[-1]["writes"], 1)

    def test_cli_defaults_run_timestamp_to_current_utc(self) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(json.dumps(candidate("memory:entity:task:T-9001")) + "\n")
            fixture_path = Path(handle.name)

        self.addCleanup(fixture_path.unlink)
        before = datetime.now(timezone.utc)
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "memory_librarian.py"),
                "--input-jsonl",
                str(fixture_path),
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        after = datetime.now(timezone.utc)

        payload = json.loads(result.stdout)
        created_at = payload["decisions"][0]["undo"]["created_at"]
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        self.assertNotEqual(created_at, "1970-01-01T00:00:00Z")
        self.assertLessEqual(before.replace(microsecond=0), created)
        self.assertLessEqual(created, after.replace(microsecond=0))


if __name__ == "__main__":
    unittest.main()
