"""Genuine Claude activity detection for headless review watchdogs.

Buffered stdout is not reliable mid-run. Prefer line-oriented incremental reads
and always treat a schema-valid structured review result at process exit as
genuine activity (even if mid-run signals were missed).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from orchestrator.review_schema import VALID_VERDICTS, parse_review_stdout

# Signals that prove Claude has started doing real work (not just process spawn).
_ACTIVITY_PATTERNS = (
    re.compile(r'"type"\s*:\s*"(?:assistant|result|tool_use|content_block_start|message_start)"', re.I),
    re.compile(r'"session_id"\s*:\s*"[^"]+"', re.I),
    re.compile(r'"sessionId"\s*:\s*"[^"]+"', re.I),
    re.compile(r'"modelUsage"\s*:', re.I),
    re.compile(r'"usage"\s*:\s*\{', re.I),
    re.compile(r'"stop_reason"\s*:', re.I),
    re.compile(r'"tool_use"', re.I),
    re.compile(r'"input_tokens"\s*:', re.I),
    re.compile(r'"verdict"\s*:\s*"(?:accepted|changes_requested|rejected)"', re.I),
)


def detect_activity_signals(text: str) -> dict[str, Any]:
    """Return activity evidence extracted from partial or final stdout/stderr text."""
    blob = text or ""
    matched = [p.pattern for p in _ACTIVITY_PATTERNS if p.search(blob)]
    session_id = None
    for pat in (
        re.compile(r'"session_id"\s*:\s*"([^"]+)"', re.I),
        re.compile(r'"sessionId"\s*:\s*"([^"]+)"'),
    ):
        m = pat.search(blob)
        if m:
            session_id = m.group(1)
            break

    verdict = None
    parsed, _errs = parse_review_stdout(blob)
    if parsed is not None and parsed.verdict in VALID_VERDICTS:
        verdict = parsed.verdict
    else:
        # Lightweight scan for verdict string without full schema
        m = re.search(r'"verdict"\s*:\s*"(accepted|changes_requested|rejected)"', blob)
        if m:
            verdict = m.group(1)

    genuine = bool(matched) or bool(session_id) or (verdict in VALID_VERDICTS)
    return {
        "genuine_activity": genuine,
        "matched_patterns": matched,
        "session_id": session_id,
        "verdict_hint": verdict,
        "bytes_scanned": len(blob.encode("utf-8", errors="replace")),
    }


def read_text_best_effort(path: Path | str | None) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.is_file():
        return ""
    try:
        # Binary-safe then decode so concurrent writers cannot raise mid-read.
        return p.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return ""


def detect_activity_from_paths(
    *paths: Path | str | None,
) -> dict[str, Any]:
    """Merge activity evidence from one or more log paths (stdout/stderr)."""
    parts: list[str] = []
    for path in paths:
        parts.append(read_text_best_effort(path))
    return detect_activity_signals("\n".join(parts))


def is_valid_structured_review_result(text: str) -> bool:
    """True when stdout contains a schema-valid review verdict."""
    verdict, errors = parse_review_stdout(text or "")
    return verdict is not None and not errors and verdict.verdict in VALID_VERDICTS


def merge_activity_with_exit_result(
    *,
    mid_run_activity: bool,
    exit_code: int | None,
    stdout: str,
    stderr: str = "",
) -> dict[str, Any]:
    """Final activity judgment after process exit.

    Exit with a schema-valid structured review result counts as genuine activity
    even if mid-run stdout was fully buffered and invisible to the watchdog.
    """
    final_text = f"{stdout or ''}\n{stderr or ''}"
    signals = detect_activity_signals(final_text)
    valid_result = is_valid_structured_review_result(stdout or "") or is_valid_structured_review_result(
        final_text
    )
    genuine = bool(mid_run_activity) or bool(signals["genuine_activity"]) or valid_result
    return {
        "genuine_activity": genuine,
        "mid_run_activity": bool(mid_run_activity),
        "valid_structured_result": valid_result,
        "session_id": signals.get("session_id"),
        "verdict_hint": signals.get("verdict_hint"),
        "exit_code": exit_code,
        "matched_patterns": signals.get("matched_patterns") or [],
    }
