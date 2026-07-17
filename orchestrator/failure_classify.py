"""Classify agent CLI failures into truthful blocked/failed states."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from orchestrator.runtime_store import (
    STATE_BLOCKED_AUTHENTICATION,
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
    re.compile(r"monthly limit", re.I),
    re.compile(r"tokens? remaining", re.I),
)

_AUTH_PATTERNS = (
    re.compile(r"unauthori[sz]ed", re.I),
    re.compile(r"authentication", re.I),
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


def classify_process_output(
    *,
    agent: str,
    adapter: str,
    exit_code: int | None,
    stdout: str = "",
    stderr: str = "",
    timed_out: bool = False,
    launch_error: str | None = None,
) -> Classification:
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

    blob = f"{stdout}\n{stderr}"
    retry_after = _parse_retry_after(blob)

    if re.search(r"max(?:imum)?[\s_-]*turns?|turn limit", blob, re.I):
        return Classification(
            process_state=STATE_MAX_TURNS,
            category="max_turns",
            detail="agent reached the bounded turn limit",
            retry_eligible=True,
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

    if exit_code not in (0, None):
        return Classification(
            process_state=STATE_FAILED,
            category="failed",
            detail=f"nonzero exit code {exit_code}",
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
            return False, "unchanged external failure fingerprint; no automatic relaunch"
        if retry_count >= max_automatic_retry:
            return False, "automatic retry budget exhausted for unchanged failure"
        return False, "unchanged failure fingerprint; no automatic relaunch"
    if retry_count >= max_automatic_retry:
        return False, "automatic retry budget exhausted"
    return True, "failure fingerprint changed"
