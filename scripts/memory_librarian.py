#!/usr/bin/env python3
"""Batchable Librarian policy skeleton for Agentic OS memory candidates.

Phase 2.1 runs in dry-run mode: it evaluates extractor output, emits candidate
decisions and undo records, and can append an audit summary. It does not write
to Cognee, call an LLM, expose MCP write tools, or run as a daemon.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.memory_extractors import REPO_ROOT, extract_repo_records
except ModuleNotFoundError:
    from memory_extractors import REPO_ROOT, extract_repo_records


DEFAULT_CONFIDENCE_THRESHOLD = 0.8
DEFAULT_CIRCUIT_BREAKER_THRESHOLD = 10
DEFAULT_RUN_TS = "1970-01-01T00:00:00Z"
AUDIT_EVENT_TYPE = "note"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def source_refs(record: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    source = record.get("source") or {}
    path = source.get("path")
    line = source.get("line")
    if path and line:
        refs.append(f"{path}:{line}")
    elif path:
        refs.append(str(path))

    for values in (record.get("refs") or {}).values():
        for value in values or []:
            ref = str(value)
            if ref not in refs:
                refs.append(ref)
    return refs


def has_citation(record: dict[str, Any]) -> bool:
    source = record.get("source") or {}
    return bool(source.get("path") and source.get("line") and source.get("id"))


def record_signature(record: dict[str, Any]) -> str:
    payload = {
        "id": record.get("id"),
        "type": record.get("type"),
        "content": record.get("content"),
        "source_refs": source_refs(record),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def undo_record(record: dict[str, Any], run_ts: str) -> dict[str, Any]:
    digest = hashlib.sha256(
        canonical_json({"id": record.get("id"), "source_refs": source_refs(record), "content": record.get("content")}).encode(
            "utf-8"
        )
    ).hexdigest()
    return {
        "write_id": f"memory-write:{digest}",
        "operation": "create",
        "record_id": record.get("id"),
        "previous_record": None,
        "new_record": record,
        "source_refs": source_refs(record),
        "created_at": run_ts,
        "created_by": "librarian",
    }


def skip_decision(record: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "kind": "candidate_decision",
        "record_id": record.get("id"),
        "action": "skip",
        "reason": reason,
        "record": record,
    }


def conflict_decision(record: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "candidate_decision",
        "record_id": record.get("id"),
        "action": "conflict",
        "reason": "same_id_different_content",
        "record": record,
        "existing_record": existing,
    }


def write_decision(record: dict[str, Any], run_ts: str, shared_writes_enabled: bool) -> dict[str, Any]:
    return {
        "kind": "candidate_decision",
        "record_id": record.get("id"),
        "action": "would_write" if not shared_writes_enabled else "write_planned",
        "reason": "policy_passed",
        "record": record,
        "undo": undo_record(record, run_ts),
    }


def run_librarian(
    records: list[dict[str, Any]],
    *,
    run_ts: str = DEFAULT_RUN_TS,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    circuit_breaker_threshold: int = DEFAULT_CIRCUIT_BREAKER_THRESHOLD,
    shared_writes_enabled: bool = False,
) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []
    seen_by_id: dict[str, dict[str, Any]] = {}
    seen_signatures: set[str] = set()
    writes = 0
    skips = 0
    conflicts = 0
    bad_candidates = 0
    circuit_breaker = False

    for record in records:
        if circuit_breaker:
            decisions.append(skip_decision(record, "circuit_breaker_open"))
            skips += 1
            continue

        record_id = str(record.get("id", ""))
        signature = record_signature(record)

        if not has_citation(record):
            decisions.append(skip_decision(record, "uncited"))
            skips += 1
            bad_candidates += 1
        elif float(record.get("confidence", 0.0)) < confidence_threshold:
            decisions.append(skip_decision(record, "low_confidence"))
            skips += 1
            bad_candidates += 1
        elif str(record.get("namespace", "")).startswith("agent/"):
            decisions.append(skip_decision(record, "private_namespace"))
            skips += 1
            bad_candidates += 1
        elif record.get("type") == "persona":
            decisions.append(skip_decision(record, "persona_record"))
            skips += 1
            bad_candidates += 1
        elif signature in seen_signatures:
            decisions.append(skip_decision(record, "duplicate"))
            skips += 1
        elif record_id in seen_by_id and record_signature(seen_by_id[record_id]) != signature:
            decisions.append(conflict_decision(record, seen_by_id[record_id]))
            conflicts += 1
            bad_candidates += 1
        else:
            decisions.append(write_decision(record, run_ts, shared_writes_enabled))
            seen_by_id[record_id] = record
            seen_signatures.add(signature)
            writes += 1

        if bad_candidates > circuit_breaker_threshold:
            circuit_breaker = True

    summary = {
        "kind": "run_summary",
        "candidates": len(records),
        "writes": writes,
        "skips": skips,
        "conflicts": conflicts,
        "circuit_breaker": circuit_breaker,
        "shared_writes_enabled": shared_writes_enabled,
        "confidence_threshold": confidence_threshold,
    }
    return {"decisions": decisions, "summary": summary}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if raw_line.strip():
            records.append(json.loads(raw_line))
    return records


def append_audit_event(root: Path, summary: dict[str, Any], *, task_id: str | None = None, ts: str | None = None) -> Path:
    event: dict[str, Any] = {
        "ts": ts or utc_now(),
        "agent": "librarian",
        "type": AUDIT_EVENT_TYPE,
        "detail": "Librarian dry-run summary",
        "counts": {
            "candidates": summary["candidates"],
            "writes": summary["writes"],
            "skips": summary["skips"],
            "conflicts": summary["conflicts"],
        },
        "circuit_breaker": summary["circuit_breaker"],
        "shared_writes_enabled": summary["shared_writes_enabled"],
        "ref": "scripts/memory_librarian.py",
    }
    if task_id:
        event["task_id"] = task_id

    log_path = root / "logs" / "agent-events.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(event) + "\n")
    return log_path


def emit_result(result: dict[str, Any], *, jsonl: bool) -> None:
    if jsonl:
        for decision in result["decisions"]:
            print(canonical_json(decision))
        print(canonical_json(result["summary"]))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run the Agentic OS Librarian policy skeleton.")
    p.add_argument("--root", default=str(REPO_ROOT), help="Repository root. Defaults to this checkout.")
    p.add_argument("--input-jsonl", help="Read candidate records from JSONL instead of running extractors.")
    p.add_argument("--jsonl", action="store_true", help="Emit candidate decisions and summary as JSONL.")
    p.add_argument("--output", help="Write output to a file instead of stdout.")
    p.add_argument("--run-ts", help="Timestamp used in generated undo records. Defaults to current UTC.")
    p.add_argument("--task-id", help="Task id for optional audit event.")
    p.add_argument("--append-audit-log", action="store_true", help="Append a note event with run counts.")
    p.add_argument("--enable-shared-writes", action="store_true", help="Mark policy-passing candidates as write-planned.")
    p.add_argument("--circuit-breaker-threshold", type=int, default=DEFAULT_CIRCUIT_BREAKER_THRESHOLD)
    return p


def main() -> int:
    args = parser().parse_args()
    root = Path(args.root)
    records = load_jsonl(Path(args.input_jsonl)) if args.input_jsonl else extract_repo_records(root)
    result = run_librarian(
        records,
        run_ts=args.run_ts or utc_now(),
        circuit_breaker_threshold=args.circuit_breaker_threshold,
        shared_writes_enabled=args.enable_shared_writes,
    )

    try:
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8", newline="\n") as handle:
                if args.jsonl:
                    for decision in result["decisions"]:
                        handle.write(canonical_json(decision) + "\n")
                    handle.write(canonical_json(result["summary"]) + "\n")
                else:
                    handle.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        else:
            emit_result(result, jsonl=args.jsonl)
    except BrokenPipeError:
        return 0

    if args.append_audit_log:
        append_audit_event(root, result["summary"], task_id=args.task_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
