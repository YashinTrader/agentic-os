"""Classify agent CLI failures into truthful blocked/failed states."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from dispatch.mcp_isolation import classify_required_mcp_failure
from orchestrator.grok_stream import terminal_event
from orchestrator.runtime_store import (
    STATE_BLOCKED_AUTHENTICATION,
    STATE_BLOCKED_EXTERNAL,
    STATE_BLOCKED_QUOTA,
    STATE_FAILED,
    STATE_FAILED_LAUNCH,
    STATE_TIMED_OUT,
    STATE_MAX_TURNS,
    FailureFingerprint,
)

_QUOTA_PATTERNS = (
    re.compile(r"quota", re.I),
    re.compile(r"rate[\s_-]?limit", re.I),
    re.compile(r"usage[\s_-]?limit", re.I),
    re.compile(r"too many requests", re.I),
    re.compile(r"\b429\b"),
    re.compile(r"\b402\b"),
    re.compile(r"monthly limit", re.I),
    re.compile(r"tokens? remaining", re.I),
    re.compile(r"usage balance", re.I),
    re.compile(r"balance exhausted", re.I),
)

_AUTH_PATTERNS = (
    re.compile(r"unauthori[sz]ed", re.I),
    re.compile(r"authentication", re.I),
    re.compile(r"failed to authenticate", re.I),
    re.compile(r"not logged in", re.I),
    re.compile(r"login required", re.I),
    re.compile(r"invalid api key", re.I),
    re.compile(r"api key", re.I),
    re.compile(r"\b401\b"),
    re.compile(r"\b403\b"),
    re.compile(r"please run .*login", re.I),
    re.compile(r"credentials?", re.I),
)

_RETRY_AFTER_PATTERNS = (
    re.compile(r"retry[- ]after[:\s]+(\d+)", re.I),
    re.compile(r"try again in\s+(\d+)\s*(seconds?|minutes?|hours?|s|m|h)?", re.I),
    re.compile(r"resets?\s+at\s+([0-9T:\-+Z.]+)", re.I),
)


@dataclass(frozen=True)
class Classification:
    process_state: str
    category: str
    detail: str
    retry_after: str | None = None
    retry_eligible: bool = False


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _parse_retry_after(text: str) -> str | None:
    for pattern in _RETRY_AFTER_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        if pattern.pattern.startswith("resets?"):
            return match.group(1)
        amount = int(match.group(1))
        unit = (match.group(2) or "s").lower() if match.lastindex and match.lastindex >= 2 else "s"
        if unit.startswith("h"):
            delta = timedelta(hours=amount)
        elif unit.startswith("m"):
            delta = timedelta(minutes=amount)
        else:
            delta = timedelta(seconds=amount)
        return (_now() + delta).isoformat().replace("+00:00", "Z")
    return None


_MAX_TURN_REASONS = {"max_turns", "maximum_turns", "max_turns_reached", "turn_limit", "error_max_turns"}
_MAX_TURN_CLI_PATTERN = re.compile(r"max(?:imum)?[\s_-]*turns?|turn limit", re.I)


def _diagnostic_text(value: Any) -> str:
    if isinstance(value, dict):
        return "\n".join(
            f"retry-after: {item}" if key == "retry_after" else _diagnostic_text(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return "\n".join(_diagnostic_text(item) for item in value)
    return str(value)


def _error_signals(stdout: str, stderr: str, *, failed_exit: bool, unknown_exit: bool = False) -> tuple[str, bool, bool]:
    """Extract terminal provider diagnostics, never tool or assistant content.

    CLIs emit JSONL or a single (possibly pretty-printed) JSON result. Plain
    stdout and stderr are CLI error channels only on a failed exit. Structured
    error messages retain nested/escaped JSON text for diagnostic matching.
    """
    diagnostics: list[str] = []
    failed = False
    max_turns = False
    for stream in (stdout, stderr):
        try:
            records = [json.loads(stream)]
        except ValueError:
            records = []
            for line in stream.splitlines():
                try:
                    records.append(json.loads(line))
                except ValueError:
                    # Recovery has no exit status. Trust explicit CLI error
                    # prefixes, while still ignoring narration and tool events.
                    if failed_exit or (unknown_exit and re.match(r'^\s*(?:API error\b|error\s*:)', line, re.I)):
                        diagnostics.append(line)
                        failed = True
                        if _MAX_TURN_CLI_PATTERN.search(line):
                            max_turns = True
        for event in records:
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if kind == "max_turns_reached":
                max_turns = True
                continue
            # Grok's single JSON result may omit the event type entirely.
            if kind is None and "result" in event and ("is_error" in event or "error" in event):
                kind = "result"
            # Do not recurse: nested events/errors can be quoted tool output.
            if not isinstance(kind, str) or kind not in {"error", "turn.failed", "result", "turn.completed", "end"}:
                continue
            reasons = [event.get("stop_reason"), event.get("stopReason"), event.get("subtype"), event.get("code")]
            bounded = any(isinstance(reason, str) and reason.lower().replace("-", "_").replace(" ", "_")
                          in _MAX_TURN_REASONS for reason in reasons)
            turns, maximum = event.get("num_turns"), event.get("max_turns")
            bounded = bounded or (type(turns) is int and type(maximum) is int
                                  and maximum > 0 and turns == maximum)
            max_turns = max_turns or bounded
            subtype = event.get("subtype")
            stop = event.get("stopReason")
            is_error = (kind in {"error", "turn.failed"} or event.get("is_error") is True
                        or bool(event.get("error")) or event.get("status") == "error"
                        or (isinstance(subtype, str) and subtype.startswith("error"))
                        or (kind == "end" and isinstance(stop, str) and
                            (stop.lower().startswith("error") or stop.lower() in {"failed", "failure"})))
            if not is_error:
                continue
            failed = True
            # These fields belong to the provider error envelope. Exclude paths,
            # tool payloads, usage counters, and successful result narration.
            for key in ("error", "message", "code", "status", "subtype", "stop_reason", "stopReason", "retry_after"):
                value = event.get(key)
                if value is not None:
                    diagnostics.append(f"retry-after: {value}" if key == "retry_after" else
                                       _diagnostic_text(value))
            if kind == "result":
                for key in ("result", "errors"):
                    value = event.get(key)
                    if value is not None:
                        diagnostics.append(_diagnostic_text(value))
            if kind in {"error", "end"} and event.get("data") is not None:
                diagnostics.append(_diagnostic_text(event["data"]))
    return "\n".join(diagnostics), failed, max_turns


def classify_process_output(
    *,
    agent: str,
    adapter: str,
    exit_code: int | None,
    stdout: str = "",
    stderr: str = "",
    timed_out: bool = False,
    launch_error: str | None = None,
    deadline_state: str | None = None,
    required_mcp_servers: list[str] | None = None,
) -> Classification:
    if deadline_state in {"failed_launch", "stalled", "timed_out"}:
        return Classification(
            process_state=deadline_state, category=deadline_state,
            detail=f"agent run deadline expired: {deadline_state}", retry_eligible=False,
        )
    if launch_error:
        return Classification(
            process_state=STATE_FAILED_LAUNCH,
            category="failed_launch",
            detail=launch_error[:500],
            retry_eligible=False,
        )
    if timed_out:
        return Classification(
            process_state=STATE_TIMED_OUT,
            category="timed_out",
            detail="process exceeded bounded timeout",
            retry_eligible=False,
        )

    blob, provider_failed, max_turns = _error_signals(
        stdout, stderr, failed_exit=exit_code not in (0, None), unknown_exit=exit_code is None,
    )
    if exit_code in (0, None) and not provider_failed and not max_turns:
        if adapter == "composer-restricted" and (exit_code != 0 or terminal_event(stdout) is None):
            return Classification(
                process_state=STATE_FAILED, category="failed",
                detail="Grok completion requires exit code 0 and a streaming end event",
                retry_eligible=False,
            )
        return Classification(
            process_state="completed", category="completed",
            detail="process completed successfully", retry_eligible=False,
        )
    retry_after = _parse_retry_after(blob)

    if max_turns:
        return Classification(
            process_state=STATE_MAX_TURNS,
            category="max_turns",
            detail="turn budget exhausted; reviewer action required: inspect preserved branch and run evidence",
            retry_eligible=False,
        )

    # Required MCP failures are external blockers (truthful; not silent).
    mcp_hit = classify_required_mcp_failure(
        required_mcp_servers=list(required_mcp_servers or []),
        stdout="",
        stderr=blob,
        exit_code=exit_code,
    )
    if mcp_hit is not None:
        return Classification(
            process_state=STATE_BLOCKED_EXTERNAL,
            category="blocked_external",
            detail=str(mcp_hit.get("detail") or "required MCP failure")[:500],
            retry_after=retry_after,
            retry_eligible=False,
        )

    for pattern in _AUTH_PATTERNS:
        if pattern.search(blob):
            return Classification(
                process_state=STATE_BLOCKED_AUTHENTICATION,
                category="blocked_authentication",
                detail=f"authentication failure matched {pattern.pattern!r}",
                retry_after=retry_after,
                retry_eligible=False,
            )

    for pattern in _QUOTA_PATTERNS:
        if pattern.search(blob):
            return Classification(
                process_state=STATE_BLOCKED_QUOTA,
                category="blocked_quota",
                detail=f"quota failure matched {pattern.pattern!r}",
                retry_after=retry_after,
                retry_eligible=bool(retry_after),
            )

    if exit_code not in (0, None) or provider_failed:
        return Classification(
            process_state=STATE_FAILED,
            category="failed",
            detail=f"nonzero exit code {exit_code}" if exit_code not in (0, None) else "structured provider error",
            retry_eligible=False,
        )

    return Classification(
        process_state="completed",
        category="completed",
        detail="process completed successfully",
        retry_eligible=False,
    )


def build_fingerprint(
    *,
    agent: str,
    adapter: str,
    classification: Classification,
    exit_code: int | None,
) -> FailureFingerprint:
    return FailureFingerprint(
        agent=agent,
        adapter=adapter,
        failure_category=classification.category,
        cli_exit_code=exit_code,
        normalized_error_type=classification.category,
        retry_after=classification.retry_after,
    )


def should_relaunch(
    *,
    previous: FailureFingerprint | None,
    current: FailureFingerprint | None,
    retry_count: int,
    max_automatic_retry: int = 1,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Return whether an automatic relaunch is allowed."""
    if previous is None:
        return True, "no prior failure fingerprint"
    if current is None:
        return True, "no current failure fingerprint"
    if previous.unchanged(current):
        if previous.failure_category in {"blocked_authentication", "blocked_quota"}:
            if previous.retry_after:
                try:
                    reset_at = datetime.fromisoformat(previous.retry_after.replace("Z", "+00:00"))
                except ValueError:
                    return False, "unchanged external failure fingerprint (unparseable retry_after)"
                clock = now or _now()
                if clock < reset_at:
                    return False, "quota/auth still blocked until retry_after"
                if retry_count >= max_automatic_retry:
                    return False, "automatic retry budget exhausted after retry_after"
                return True, "retry_after elapsed; one automatic retry allowed"
            # Wake relaunch stays off. The supervisor tick schedules the bounded
            # retry (backoff, retry_after, or a quota-free probe).
            return False, "unchanged external failure fingerprint; no automatic relaunch"
        if retry_count >= max_automatic_retry:
            return False, "automatic retry budget exhausted for unchanged failure"
        return False, "unchanged failure fingerprint; no automatic relaunch"
    if retry_count >= max_automatic_retry:
        return False, "automatic retry budget exhausted"
    return True, "failure fingerprint changed"
