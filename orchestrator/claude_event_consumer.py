"""Persistent consumer for terminal builder pokes and headless Claude reviews."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dispatch.atomic_io import atomic_create_json, atomic_write_json
from dispatch.orchestrator_pokes import list_orchestrator_pokes
from orchestrator.review_schema import VALID_VERDICTS

Processor = Callable[..., dict[str, Any]]
STARTUP_PID_TIMEOUT_SECONDS = 30
STARTUP_ACTIVITY_TIMEOUT_SECONDS = 90
UNHANDLED_ALERT_SECONDS = 300
MAX_ATTEMPTS = 2


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def watcher_dir(repo_root: Path) -> Path:
    return repo_root / "runtime" / "dispatch" / "claude_event_consumer"


def watcher_status_path(repo_root: Path) -> Path:
    return watcher_dir(repo_root) / "status.json"


def load_watcher_status(repo_root: Path) -> dict[str, Any]:
    path = watcher_status_path(repo_root)
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def event_fingerprint(poke: dict[str, Any]) -> str:
    stable = "\0".join(str(poke.get(k) or "") for k in ("source", "assignment_id", "task_id", "event"))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


DEFAULT_REVIEW_TIMEOUT_SECONDS = 1800


def _default_processor(repo_root: Path, **kwargs: Any) -> dict[str, Any]:
    from orchestrator.review_dispatcher import process_one_review

    # activity_timeout is only the startup genuine-activity budget.
    # Full review wall-clock timeout must remain large enough for real Claude work.
    return process_one_review(
        repo_root,
        assignment_id=str(kwargs["assignment_id"]),
        timeout_seconds=int(kwargs.get("timeout_seconds") or DEFAULT_REVIEW_TIMEOUT_SECONDS),
        activity_timeout_seconds=int(
            kwargs.get("activity_timeout_seconds") or STARTUP_ACTIVITY_TIMEOUT_SECONDS
        ),
        apply=True,
    )


def has_genuine_activity(
    *,
    pid: Any,
    session_id: Any,
    verdict: Any,
    status: Any = None,
    activity_evidence: dict[str, Any] | None = None,
) -> bool:
    """True when Claude did real work, not merely that a process was spawned.

    A schema-valid structured verdict at exit always counts — even if mid-run
    stdout was buffered and invisible to the activity watchdog.
    """
    if activity_evidence and activity_evidence.get("genuine_activity"):
        return True
    if verdict in VALID_VERDICTS:
        return True
    if session_id:
        return True
    if status == "completed" and verdict in VALID_VERDICTS:
        return True
    return False


class ClaudeEventConsumer:
    """Claim one poke at a time and archive it only after a recorded verdict."""

    def __init__(self, repo_root: Path, *, processor: Processor | None = None) -> None:
        self.repo_root = Path(repo_root)
        self.processor = processor or (lambda **kw: _default_processor(self.repo_root, **kw))

    def _status(self, **updates: Any) -> dict[str, Any]:
        pokes, _ = list_orchestrator_pokes(self.repo_root)
        ages = []
        now = datetime.now(timezone.utc)
        for poke in pokes:
            try:
                ages.append(max(0, int((now - _parse_time(str(poke["created_at"]))).total_seconds())))
            except (KeyError, TypeError, ValueError):
                continue
        current = load_watcher_status(self.repo_root)
        current.update({
            "schema_version": "1.0",
            "heartbeat_at": _now(),
            "oldest_pending_poke_age_seconds": max(ages, default=0),
            "alert_active": max(ages, default=0) > UNHANDLED_ALERT_SECONDS,
            **updates,
        })
        watcher_dir(self.repo_root).mkdir(parents=True, exist_ok=True)
        atomic_write_json(watcher_status_path(self.repo_root), current)
        return current

    def _archive(self, poke: dict[str, Any]) -> None:
        source = self.repo_root / str(poke["source_path"])
        target = self.repo_root / "runtime" / "dispatch" / "pokes" / "consumed" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)

    def process_once(self) -> dict[str, Any]:
        pokes, errors = list_orchestrator_pokes(self.repo_root)
        if not pokes:
            self._status(active_review_assignment=None, pid=None)
            return {"status": "idle", "errors": errors}

        eligible = [
            item for item in pokes
            if item.get("event") == "assignment_completed" and item.get("source") != "claude"
        ]
        if not eligible:
            self._status(active_review_assignment=None, last_blocker=None)
            return {"status": "idle", "reason": "no terminal builder pokes", "errors": errors}

        poke = eligible[0]
        fingerprint = event_fingerprint(poke)
        resolved_path = watcher_dir(self.repo_root) / "resolved" / f"{fingerprint}.json"
        transitions = ["pending"]
        if resolved_path.is_file():
            self._archive(poke)
            self._status(last_event_fingerprint=fingerprint)
            return {"status": "deduplicated", "fingerprint": fingerprint, "transitions": transitions}

        claim_path = watcher_dir(self.repo_root) / "claims" / f"{fingerprint}.json"
        claim_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            atomic_create_json(claim_path, {
                "fingerprint": fingerprint, "poke_id": poke.get("poke_id"),
                "assignment_id": poke.get("assignment_id"), "claimed_at": _now(),
            })
        except FileExistsError:
            self._status(last_blocker="event already claimed", last_event_fingerprint=fingerprint)
            return {"status": "deferred", "fingerprint": fingerprint, "transitions": transitions}

        transitions.append("claimed")
        last: dict[str, Any] = {}
        try:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                transitions.append("review_starting")
                self._status(
                    active_review_assignment=poke.get("assignment_id"), attempt_count=attempt,
                    pid=None, claude_session_id=None, last_blocker=None,
                    last_event_fingerprint=fingerprint, lifecycle_state="review_starting",
                )
                started = time.monotonic()
                try:
                    last = self.processor(
                        assignment_id=str(poke.get("assignment_id") or ""),
                        poke=poke,
                        pid_timeout_seconds=STARTUP_PID_TIMEOUT_SECONDS,
                        activity_timeout_seconds=STARTUP_ACTIVITY_TIMEOUT_SECONDS,
                    )
                except Exception as exc:
                    last = {"status": "failed_launch", "blocked_reason": str(exc)}

                pid = last.get("pid")
                verdict = last.get("verdict")
                session_id = last.get("session_id")
                evidence = last.get("activity_evidence") if isinstance(last.get("activity_evidence"), dict) else None
                genuine_activity = has_genuine_activity(
                    pid=pid,
                    session_id=session_id,
                    verdict=verdict,
                    status=last.get("status"),
                    activity_evidence=evidence,
                )
                # PID proves process spawn; genuine activity proves Claude worked.
                launch_ok = bool(pid) and genuine_activity

                # Successful structured completion must never be rewritten to failed_launch.
                # Exit-with-valid-verdict counts even when session_id was buffered/late.
                completed_ok = (
                    last.get("status") == "completed"
                    and verdict in VALID_VERDICTS
                    and (bool(pid) or bool(last.get("recovered")))
                )
                if completed_ok:
                    # Ensure review_running appears in the evidence chain when activity is proven.
                    if "review_running" not in transitions:
                        transitions.append("review_running")
                    self._status(
                        lifecycle_state="review_running",
                        pid=pid,
                        claude_session_id=session_id,
                        attempt_count=attempt,
                    )
                    resolution = {
                        "fingerprint": fingerprint,
                        "assignment_id": poke.get("assignment_id"),
                        "review_run_id": last.get("review_run_id"),
                        "pid": pid,
                        "session_id": session_id,
                        "verdict": verdict,
                        "assignment_status": last.get("assignment_status"),
                        "recorded_at": _now(),
                        "attempt_count": attempt,
                        "activity_evidence": evidence,
                    }
                    resolved_path.parent.mkdir(parents=True, exist_ok=True)
                    atomic_write_json(resolved_path, resolution)
                    transitions.append("resolved")
                    self._archive(poke)
                    self._status(
                        lifecycle_state="resolved",
                        active_review_assignment=None,
                        pid=pid,
                        claude_session_id=session_id,
                        attempt_count=attempt,
                        last_verdict=verdict,
                        last_blocker=None,
                    )
                    return {"status": "resolved", "transitions": transitions, **resolution}

                if launch_ok:
                    transitions.append("review_running")
                    self._status(
                        lifecycle_state="review_running",
                        pid=pid,
                        claude_session_id=session_id,
                        attempt_count=attempt,
                    )
                else:
                    if not pid:
                        reason = str(last.get("blocked_reason") or "PID startup watchdog expired")
                    elif not genuine_activity:
                        reason = str(
                            last.get("blocked_reason") or "genuine activity watchdog expired"
                        )
                    else:
                        reason = str(last.get("blocked_reason") or last.get("status") or "failed_launch")
                    last = {**last, "status": "failed_launch", "blocked_reason": reason}

                if last.get("status") != "failed_launch":
                    break

            blocker = str(last.get("blocked_reason") or last.get("status") or "review failed")
            self._status(
                lifecycle_state="failed_launch", active_review_assignment=None,
                attempt_count=MAX_ATTEMPTS, last_blocker=blocker,
                pid=last.get("pid"), claude_session_id=last.get("session_id"),
            )
            return {
                "status": "failed_launch", "fingerprint": fingerprint,
                "attempt_count": MAX_ATTEMPTS, "last_blocker": blocker,
                "transitions": transitions,
            }
        finally:
            if claim_path.exists():
                claim_path.unlink()

    def run_forever(self, *, poll_seconds: float = 5.0) -> int:
        while True:
            report = self.process_once()
            print(json.dumps(report, sort_keys=True), flush=True)
            time.sleep(max(0.1, poll_seconds))
