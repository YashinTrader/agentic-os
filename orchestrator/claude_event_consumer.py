"""Persistent consumer for terminal builder pokes and headless Claude reviews."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from orchestrator import consumer_claims
from dispatch.work_lock import WorkLockError
from orchestrator.process_ownership import process_start_time
from orchestrator.layer_heartbeat import tick
from root_paths import root_metadata
from dispatch.atomic_io import atomic_write_json
from dispatch.orchestrator_pokes import list_orchestrator_pokes
from orchestrator.agent_launcher import resolve_executable
from orchestrator.review_schema import VALID_VERDICTS

Processor = Callable[..., dict[str, Any]]
STARTUP_PID_TIMEOUT_SECONDS = 30
STARTUP_ACTIVITY_TIMEOUT_SECONDS = 90
UNHANDLED_ALERT_SECONDS = 300
MAX_ATTEMPTS = 2
INITIAL_BACKOFF_SECONDS = 300
MAX_BACKOFF_SECONDS = 6 * 60 * 60
PROBE_INTERVAL_SECONDS = 10 * 60
DEFERRED_ALERT_SECONDS = 6 * 60 * 60


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def deferred_path(repo_root: Path, fingerprint: str) -> Path:
    return watcher_dir(repo_root) / "deferred" / f"{fingerprint}.json"


def backoff_seconds(attempt: int) -> int:
    """Return the bounded delay after a one-based failed evaluation attempt."""
    return min(INITIAL_BACKOFF_SECONDS * (2 ** max(0, attempt - 1)), MAX_BACKOFF_SECONDS)


def classify_blocked_on(result: dict[str, Any]) -> str:
    reason = str(result.get("blocked_reason") or result.get("last_blocker") or result.get("status") or "")
    lowered = reason.lower()
    if any(word in lowered for word in ("auth", "login", "logged in", "credential")):
        return "auth:claude"
    if any(word in lowered for word in ("quota", "rate limit", "capacity", "balance")):
        return "quota:claude"
    return "failure_fingerprint:" + hashlib.sha256(reason.encode("utf-8")).hexdigest()[:16]


def default_condition_probe(blocked_on: str) -> bool:
    """Use a cheap local CLI auth query; other conditions rely on backoff."""
    if blocked_on != "auth:claude":
        return False
    try:
        executable = resolve_executable("claude")
        if not executable:
            return False
        completed = subprocess.run(
            [executable, "auth", "status"], capture_output=True, text=True,
            timeout=15, check=False, shell=False,
        )
        if completed.returncode != 0:
            return False
        status = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError):
        return False
    return isinstance(status, dict) and status.get("loggedIn") is True


def _default_processor(repo_root: Path, **kwargs: Any) -> dict[str, Any]:
    from orchestrator.review_dispatcher import process_one_review

    return process_one_review(
        repo_root,
        assignment_id=str(kwargs["assignment_id"]),
        timeout_seconds=1800,
        activity_timeout_seconds=int(kwargs.get("activity_timeout_seconds") or STARTUP_ACTIVITY_TIMEOUT_SECONDS),
        apply=True,
        on_review_started=kwargs.get("on_review_started"),
    )


class ClaudeEventConsumer:
    """Claim one poke at a time and archive it only after a recorded verdict."""

    def __init__(
        self, repo_root: Path, *, processor: Processor | None = None,
        condition_probe: Callable[[str], bool] | None = None,
        now: Callable[[], datetime] | None = None,
        state_logger: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.root_audit = root_metadata(self.repo_root)
        self.processor = processor or (lambda **kw: _default_processor(self.repo_root, **kw))
        self.condition_probe = condition_probe or default_condition_probe
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.state_logger = state_logger
        self.consumer_token = uuid.uuid4().hex
        self.consumer_pid = os.getpid()
        self.consumer_start_time = process_start_time(self.consumer_pid)

    def _emit(self, event: str, **details: Any) -> None:
        if event == "claimed":
            tick(progress=True)
        if self.state_logger:
            self.state_logger({"at": _format_time(self.now()), "event": event, **details})

    def _load_deferred(self, fingerprint: str) -> dict[str, Any] | None:
        path = deferred_path(self.repo_root, fingerprint)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def _record_deferral(self, fingerprint: str, blocked_on: str) -> dict[str, Any]:
        now = self.now()
        previous = self._load_deferred(fingerprint) or {}
        same_reason = previous.get("blocked_on") == blocked_on
        attempt = int(previous.get("attempt_count", 0)) + 1 if same_reason else 1
        state = {
            "fingerprint": fingerprint,
            "blocked_on": blocked_on,
            "deferred_since": previous.get("deferred_since") if same_reason else _format_time(now),
            "next_eligible_at": _format_time(now + timedelta(seconds=backoff_seconds(attempt))),
            "attempt_count": attempt,
            "last_probe_at": previous.get("last_probe_at") if same_reason else None,
        }
        path = deferred_path(self.repo_root, fingerprint)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, state)
        if not previous or not same_reason:
            self._emit("deferred", fingerprint=fingerprint, blocked_on=blocked_on)
        return state

    def _deferred_is_eligible(self, state: dict[str, Any]) -> bool:
        now = self.now()
        if now >= _parse_time(str(state["next_eligible_at"])):
            return True
        last_probe = state.get("last_probe_at")
        may_probe = not last_probe or (now - _parse_time(str(last_probe))).total_seconds() >= PROBE_INTERVAL_SECONDS
        if may_probe:
            state["last_probe_at"] = _format_time(now)
            atomic_write_json(deferred_path(self.repo_root, str(state["fingerprint"])), state)
            if self.condition_probe(str(state["blocked_on"])):
                self._emit("condition_cleared", fingerprint=state["fingerprint"], blocked_on=state["blocked_on"])
                return True
        return False

    def _status(self, **updates: Any) -> dict[str, Any]:
        pokes, _ = list_orchestrator_pokes(self.repo_root)
        ages = []
        now = self.now()
        for poke in pokes:
            try:
                ages.append(max(0, int((now - _parse_time(str(poke["created_at"]))).total_seconds())))
            except (KeyError, TypeError, ValueError):
                continue
        current = load_watcher_status(self.repo_root)
        deferred_states = [self._load_deferred(path.stem) for path in (watcher_dir(self.repo_root) / "deferred").glob("*.json")]
        escalated = [
            state for state in deferred_states if state and
            (now - _parse_time(str(state["deferred_since"]))).total_seconds() > DEFERRED_ALERT_SECONDS
        ]
        was_escalated = bool(current.get("deferred_escalation_active"))
        stale = consumer_claims.stale_claims(self.repo_root, now, consumer_token=self.consumer_token)
        current.update({
            **self.root_audit,
            "schema_version": "1.0",
            "heartbeat_at": _now(),
            "oldest_pending_poke_age_seconds": max(ages, default=0),
            "alert_active": max(ages, default=0) > UNHANDLED_ALERT_SECONDS or bool(escalated) or bool(stale),
            "stale_claim_alert_active": bool(stale),
            "stale_claims": stale,
            "deferred_escalation_active": bool(escalated),
            "deferred_blocked_on": sorted({str(state["blocked_on"]) for state in escalated}),
            "last_tick_at": _format_time(now),
            **updates,
        })
        watcher_dir(self.repo_root).mkdir(parents=True, exist_ok=True)
        atomic_write_json(watcher_status_path(self.repo_root), current)
        if escalated and not was_escalated:
            self._emit("deferred_escalated", blocked_on=current["deferred_blocked_on"])
        return current

    def _archive(self, poke: dict[str, Any]) -> None:
        source = self.repo_root / str(poke["source_path"])
        target = self.repo_root / "runtime" / "dispatch" / "pokes" / "consumed" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)

    def process_once(self) -> dict[str, Any]:
        # Reset process-local lifecycle every tick; persisted status is diagnostic history.
        self._status(lifecycle_state="idle", active_review_assignment=None, pid=None,
                     claude_session_id=None, last_blocker=None)
        pokes, errors = list_orchestrator_pokes(self.repo_root)
        eligible = [item for item in pokes
                    if item.get("event") == "assignment_completed" and item.get("source") != "claude"]
        skipped = None
        deduplicated = None
        for poke in eligible:
            fingerprint = event_fingerprint(poke)
            resolved_path = watcher_dir(self.repo_root) / "resolved" / f"{fingerprint}.json"
            transitions = ["pending"]
            if resolved_path.is_file():
                try:
                    self._archive(poke)
                except FileNotFoundError:
                    pass  # Another consumer archived the same conclusive event.
                deduplicated = {"status": "deduplicated", "fingerprint": fingerprint, "transitions": transitions}
                continue
            deferred = self._load_deferred(fingerprint)
            if deferred and not self._deferred_is_eligible(deferred):
                skipped = {"status": "deferred", **deferred, "transitions": transitions}
                continue
            payload = {
                "fingerprint": fingerprint, "poke_id": poke.get("poke_id"),
                "assignment_id": poke.get("assignment_id"), "claimed_at": _format_time(self.now()),
                "consumer_pid": self.consumer_pid, "consumer_start_time": self.consumer_start_time,
                "consumer_token": self.consumer_token, "review_pid": None, "review_start_time": None,
            }
            try:
                acquired, recovered = consumer_claims.acquire(self.repo_root, fingerprint, payload)
            except (OSError, ValueError, WorkLockError):
                acquired, recovered = False, None
            if not acquired:
                skipped = {"status": "deferred", "fingerprint": fingerprint,
                           "last_blocker": "event already claimed", "transitions": transitions}
                continue
            if recovered:
                self._emit("claim_recovered", reason=recovered["reason"], prior_owner=recovered["prior_owner"],
                           fingerprint=fingerprint)
            self._emit("claimed", fingerprint=fingerprint, assignment_id=poke.get("assignment_id"))
            break
        else:
            current = load_watcher_status(self.repo_root)
            stale = consumer_claims.stale_claims(self.repo_root, self.now(), consumer_token=self.consumer_token)
            self._status(lifecycle_state="blocked_stale_claim" if stale else "idle",
                         active_review_assignment=None, pid=None,
                         last_blocker=(skipped or {}).get("blocked_on") or (skipped or {}).get("last_blocker"),
                         idle_ticks=int(current.get("idle_ticks", 0)) + 1)
            return skipped or deduplicated or {"status": "idle", "errors": errors}

        child_pid = None

        def review_started(pid, start):
            nonlocal child_pid
            child_pid = pid
            consumer_claims.update_child(self.repo_root, fingerprint, self.consumer_token, pid, start)

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
                        on_review_started=review_started,
                        pid_timeout_seconds=STARTUP_PID_TIMEOUT_SECONDS,
                        activity_timeout_seconds=STARTUP_ACTIVITY_TIMEOUT_SECONDS,
                    )
                except Exception as exc:
                    last = {"status": "failed_launch", "blocked_reason": str(exc)}

                pid = last.get("pid")
                if pid:
                    review_started(pid, last.get("process_start_time") or process_start_time(pid))
                verdict = last.get("verdict")
                session_id = last.get("session_id")
                valid_verdict = verdict in VALID_VERDICTS
                # A schema-valid result is conclusive activity even when stdout was buffered.
                genuine_activity = bool(session_id) or valid_verdict or bool(last.get("activity_events"))
                launch_ok = bool(pid) and genuine_activity
                if launch_ok:
                    tick(progress=True)
                    transitions.append("review_running")
                    self._status(
                        lifecycle_state="review_running", pid=pid,
                        claude_session_id=session_id, attempt_count=attempt,
                    )
                elif last.get("status") not in {"failed_launch", "stalled", "timed_out"} and (last.get("status") == "completed" or not pid or not genuine_activity):
                    reason = str(last.get("blocked_reason") or (
                        "PID startup watchdog expired" if not pid else "genuine activity watchdog expired"
                    ))
                    last = {**last, "status": "failed_launch", "blocked_reason": reason}

                if valid_verdict and bool(pid):
                    resolution = {
                        "fingerprint": fingerprint, "assignment_id": poke.get("assignment_id"),
                        "review_run_id": last.get("review_run_id"), "pid": pid,
                        "session_id": session_id, "verdict": verdict,
                        "assignment_status": last.get("assignment_status"),
                        "recorded_at": _now(), "attempt_count": attempt,
                    }
                    resolved_path.parent.mkdir(parents=True, exist_ok=True)
                    atomic_write_json(resolved_path, resolution)
                    deferred_path(self.repo_root, fingerprint).unlink(missing_ok=True)
                    tick(progress=True)
                    transitions.append("resolved")
                    self._archive(poke)
                    self._status(
                        lifecycle_state="resolved", active_review_assignment=None,
                        pid=pid, claude_session_id=session_id, attempt_count=attempt,
                        last_verdict=verdict, last_blocker=None,
                    )
                    return {"status": "resolved", "transitions": transitions, **resolution}

                # Retry only pre-PID startup failures. One observed child is the
                # tick's review launch, even if it never produces activity.
                if last.get("status") != "failed_launch" or child_pid:
                    break

            blocker = str(last.get("blocked_reason") or last.get("status") or "review failed")
            blocked_on = classify_blocked_on(last)
            deferred = self._record_deferral(fingerprint, blocked_on)
            self._status(
                lifecycle_state=last.get("status") if last.get("status") in {"stalled", "timed_out"} else "failed_launch", active_review_assignment=None,
                attempt_count=attempt, last_blocker=blocker,
                pid=last.get("pid"), claude_session_id=last.get("session_id"), blocked_on=blocked_on,
            )
            return {
                "status": "deferred", "fingerprint": fingerprint, "blocked_on": blocked_on,
                "deferred_since": deferred["deferred_since"], "next_eligible_at": deferred["next_eligible_at"],
                "attempt_count": attempt, "last_blocker": blocker,
                "transitions": transitions,
            }
        finally:
            consumer_claims.finish(self.repo_root, fingerprint, self.consumer_token)

    def run_forever(self, *, poll_seconds: float = 5.0) -> int:
        while True:
            tick()
            self.process_once()
            time.sleep(max(0.1, poll_seconds))
