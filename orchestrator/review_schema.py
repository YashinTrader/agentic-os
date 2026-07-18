"""Strict JSON schema and validation for Claude reviewer structured verdicts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

VALID_VERDICTS = frozenset({"accepted", "changes_requested", "rejected"})
VALID_SEVERITIES = frozenset({"critical", "high", "medium", "low"})
VALID_NEXT_AGENTS = frozenset({"composer", "codex", "grok"})

REVIEW_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "verdict",
        "summary",
        "repository_integrity",
        "tests",
        "findings",
        "required_changes",
        "next_assignment",
    ],
    "properties": {
        "verdict": {"type": "string", "enum": sorted(VALID_VERDICTS)},
        "summary": {"type": "string", "minLength": 1},
        "repository_integrity": {
            "type": "object",
            "additionalProperties": False,
            "required": ["verified", "branch", "local_sha", "remote_sha"],
            "properties": {
                "verified": {"type": "boolean"},
                "branch": {"type": "string"},
                "local_sha": {"type": "string"},
                "remote_sha": {"type": "string"},
            },
        },
        "tests": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["command", "exit_code", "result"],
                "properties": {
                    "command": {"type": "string"},
                    "exit_code": {"type": "integer"},
                    "result": {"type": "string"},
                },
            },
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["severity", "title", "detail", "required"],
                "properties": {
                    "severity": {"type": "string", "enum": sorted(VALID_SEVERITIES)},
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "required": {"type": "boolean"},
                },
            },
        },
        "required_changes": {"type": "array", "items": {"type": "string"}},
        "next_assignment": {
            "type": "object",
            "additionalProperties": False,
            "required": ["required", "task_id", "goal", "assigned_to"],
            "properties": {
                "required": {"type": "boolean"},
                "task_id": {"type": ["string", "null"]},
                "goal": {"type": ["string", "null"]},
                "assigned_to": {"type": ["string", "null"]},
            },
        },
    },
}


@dataclass
class ReviewVerdict:
    verdict: str
    summary: str
    repository_integrity: dict[str, Any]
    tests: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    required_changes: list[str] = field(default_factory=list)
    next_assignment: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "summary": self.summary,
            "repository_integrity": self.repository_integrity,
            "tests": self.tests,
            "findings": self.findings,
            "required_changes": self.required_changes,
            "next_assignment": self.next_assignment,
        }


def schema_json_string() -> str:
    return json.dumps(REVIEW_JSON_SCHEMA, separators=(",", ":"))


def _is_sha40(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{40}", value or ""))


def validate_review_payload(data: Any) -> tuple[ReviewVerdict | None, list[str]]:
    """Validate a Python object against the review contract (strict subset checks)."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return None, ["review payload must be a JSON object"]

    verdict = str(data.get("verdict", "")).strip()
    if verdict not in VALID_VERDICTS:
        errors.append(f"invalid verdict: {verdict!r}")

    summary = str(data.get("summary", "")).strip()
    if not summary:
        errors.append("summary must be a non-empty string")

    integrity = data.get("repository_integrity")
    if not isinstance(integrity, dict):
        errors.append("repository_integrity must be an object")
        integrity = {}
    else:
        if not isinstance(integrity.get("verified"), bool):
            errors.append("repository_integrity.verified must be boolean")
        for key in ("branch", "local_sha", "remote_sha"):
            if not isinstance(integrity.get(key), str) or not str(integrity.get(key)).strip():
                errors.append(f"repository_integrity.{key} must be a non-empty string")
        local_sha = str(integrity.get("local_sha") or "")
        remote_sha = str(integrity.get("remote_sha") or "")
        if local_sha and not _is_sha40(local_sha):
            errors.append("repository_integrity.local_sha must be 40-char hex")
        if remote_sha and not _is_sha40(remote_sha):
            errors.append("repository_integrity.remote_sha must be 40-char hex")

    tests = data.get("tests")
    if not isinstance(tests, list):
        errors.append("tests must be an array")
        tests = []
    else:
        for i, item in enumerate(tests):
            if not isinstance(item, dict):
                errors.append(f"tests[{i}] must be an object")
                continue
            if not isinstance(item.get("command"), str):
                errors.append(f"tests[{i}].command must be string")
            if not isinstance(item.get("exit_code"), int):
                errors.append(f"tests[{i}].exit_code must be integer")
            if not isinstance(item.get("result"), str):
                errors.append(f"tests[{i}].result must be string")

    findings = data.get("findings")
    if not isinstance(findings, list):
        errors.append("findings must be an array")
        findings = []
    else:
        for i, item in enumerate(findings):
            if not isinstance(item, dict):
                errors.append(f"findings[{i}] must be an object")
                continue
            sev = str(item.get("severity", ""))
            if sev not in VALID_SEVERITIES:
                errors.append(f"findings[{i}].severity invalid: {sev!r}")
            if not isinstance(item.get("title"), str) or not item.get("title"):
                errors.append(f"findings[{i}].title required")
            if not isinstance(item.get("detail"), str):
                errors.append(f"findings[{i}].detail must be string")
            if not isinstance(item.get("required"), bool):
                errors.append(f"findings[{i}].required must be boolean")

    required_changes = data.get("required_changes")
    if not isinstance(required_changes, list) or not all(isinstance(x, str) for x in required_changes):
        errors.append("required_changes must be an array of strings")
        required_changes = []

    next_assignment = data.get("next_assignment")
    if not isinstance(next_assignment, dict):
        errors.append("next_assignment must be an object")
        next_assignment = {}
    else:
        if not isinstance(next_assignment.get("required"), bool):
            errors.append("next_assignment.required must be boolean")
        for key in ("task_id", "goal", "assigned_to"):
            val = next_assignment.get(key)
            if val is not None and not isinstance(val, str):
                errors.append(f"next_assignment.{key} must be string or null")
        assigned = next_assignment.get("assigned_to")
        if isinstance(assigned, str) and assigned and assigned not in VALID_NEXT_AGENTS:
            errors.append(f"next_assignment.assigned_to invalid: {assigned!r}")
        if next_assignment.get("required") is True and not (
            next_assignment.get("task_id") and next_assignment.get("goal") and next_assignment.get("assigned_to")
        ):
            errors.append("next_assignment.required true needs task_id, goal, assigned_to")

    if verdict == "accepted" and isinstance(integrity, dict) and integrity.get("verified") is not True:
        errors.append("accepted verdict requires repository_integrity.verified true")
    if verdict == "changes_requested" and not required_changes and not any(
        isinstance(f, dict) and f.get("required") for f in findings
    ):
        errors.append("changes_requested requires required_changes or required findings")
    if verdict == "rejected" and not summary:
        errors.append("rejected verdict requires summary")

    if errors:
        return None, errors

    return (
        ReviewVerdict(
            verdict=verdict,
            summary=summary,
            repository_integrity=dict(integrity),
            tests=list(tests),
            findings=list(findings),
            required_changes=list(required_changes),
            next_assignment=dict(next_assignment),
            raw=dict(data),
        ),
        [],
    )


def _stdout_capture_snippet(text: str, *, limit: int = 800) -> str:
    """Compact non-secret stdout for invalid_structured_output diagnostics."""
    compact = re.sub(r"\s+", " ", (text or "").strip())
    if len(compact) > limit:
        return compact[:limit] + "…"
    return compact


def parse_review_stdout(stdout: str) -> tuple[ReviewVerdict | None, list[str]]:
    """Extract structured verdict from Claude CLI stdout (json result envelope or raw object).

    Claude ``--output-format json`` wraps the model payload in an envelope such as
    ``{"type":"result","result":"<string or object>","session_id":"..."}``. Accept
    either a top-level verdict object or the nested ``result`` payload. Non-JSON
    conversational prose is reported as parse failure with a captured stdout snippet
    so operators can diagnose prompt-delivery / schema failures.
    """
    text = (stdout or "").strip()
    if not text:
        return None, ["empty stdout"]

    capture = f"stdout_capture: {_stdout_capture_snippet(text)}"
    candidates: list[str] = [text]
    # Claude --output-format json wraps in {"type":"result","result":"..."} or nested JSON.
    try:
        outer = json.loads(text)
    except json.JSONDecodeError:
        outer = None
    if isinstance(outer, dict):
        if "verdict" in outer:
            return validate_review_payload(outer)
        # Prefer structured_output when Claude fills the schema field (most reliable).
        structured = outer.get("structured_output")
        if isinstance(structured, dict) and "verdict" in structured:
            return validate_review_payload(structured)
        result_field = outer.get("result")
        if isinstance(result_field, dict) and "verdict" in result_field:
            return validate_review_payload(result_field)
        if isinstance(result_field, str):
            stripped = result_field.strip()
            if stripped:
                candidates.append(stripped)
            # Try fenced JSON in prose result
            fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", result_field, re.S)
            if fence:
                candidates.append(fence.group(1))
            # Try first {...} blob only when it looks like a verdict object
            brace = re.search(r"\{[^{}]*\"verdict\"[^{}]*\}|\{.*\"verdict\".*\}", result_field, re.S)
            if brace:
                candidates.append(brace.group(0))
            elif stripped and not stripped.startswith("{") and not (
                isinstance(structured, dict) and "verdict" in structured
            ):
                # Envelope present but result is plain prose (classic Windows argv mangling).
                return None, [
                    "claude result envelope contains non-JSON prose (no structured verdict)",
                    capture,
                ]

    last_errors = ["no JSON object found in stdout"]
    for cand in candidates:
        try:
            data = json.loads(cand)
        except json.JSONDecodeError as exc:
            last_errors = [f"json decode failed: {exc}"]
            continue
        if isinstance(data, dict) and "verdict" not in data and isinstance(data.get("result"), (str, dict)):
            # Nested envelope without unwrapping above (e.g. double-encoded).
            continue
        verdict, errors = validate_review_payload(data)
        if verdict is not None:
            return verdict, []
        last_errors = errors
    return None, last_errors + [capture]
