"""Bounded condition retry for builder runs blocked on quota or authentication.

A blocked run is not relaunched on the next wake. The supervisor tick re-evaluates
it without a new wake and relaunches at most once per eligibility window when:

- a parsed ``retry_after`` has elapsed, or
- the exponential backoff has elapsed (15 minutes, doubling, capped at 6 hours), or
- a cheap local probe reports the condition cleared.

Free authentication probes are limited to once per provider per 10 minutes.
Quota recovery uses separately persisted, owner-configured hourly paid probes.

Discovery (do not call ``grok status``; it opens the TUI):

- grok / composer: no non-mutating status or auth command. Probe is none.
  Auth eligibility is backoff or ``retry_after`` only.
- codex: ``codex login status`` (resolved executable, ``shell=False``, exit code).
  That command observes login, not remaining quota, so it can clear ``auth:codex``
  only. Quota uses the separately rate-limited paid probe.
- claude: the M1-02 ``claude auth status`` probe (``auth:claude`` only).
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from dispatch.assignment_channel import read_assignment, set_assignment_status
from dispatch.atomic_io import atomic_write_json
from dispatch.work_lock import WorkLockError, status as lock_status
from orchestrator.agent_launcher import resolve_executable
from orchestrator.quota_probe import probe_blocked_providers
from orchestrator.runtime_store import (
    STATE_BLOCKED_AUTHENTICATION,
    STATE_BLOCKED_EXTERNAL,
    STATE_BLOCKED_QUOTA,
    RunState,
    list_supervisor_runs,
    save_run_state,
)

INITIAL_BACKOFF_SECONDS = 15 * 60
MAX_BACKOFF_SECONDS = 6 * 60 * 60
PROBE_INTERVAL_SECONDS = 10 * 60
MAX_CONDITION_RETRIES = 4

CONDITION_STATES = frozenset({STATE_BLOCKED_QUOTA, STATE_BLOCKED_AUTHENTICATION})
Probe = Callable[[str], bool]


def format_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def clock_from(config: object) -> datetime:
    fn = getattr(config, "now", None)
    if fn is None:
        return datetime.now(timezone.utc)
    value = fn()
    if not isinstance(value, datetime):
        raise TypeError("supervisor clock must return datetime")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def provider_for_agent(agent: str) -> str:
    name = (agent or "").strip().lower()
    if name in {"composer", "grok", "grok-build"}:
        return "grok"
    if name == "codex":
        return "codex"
    if name == "claude":
        return "claude"
    return name or "unknown"


def blocked_on_for(category: str, agent: str) -> str:
    kind = "auth" if "auth" in (category or "") else "quota"
    return f"{kind}:{provider_for_agent(agent)}"


def provider_of(blocked_on: str) -> str:
    if ":" not in (blocked_on or ""):
        return ""
    return blocked_on.split(":", 1)[1].strip().lower()


def backoff_seconds(attempts: int) -> int:
    """Wait after ``attempts`` automatic retries have already been started."""
    return min(INITIAL_BACKOFF_SECONDS * (2 ** max(0, attempts)), MAX_BACKOFF_SECONDS)


def schedule_next_eligible(now: datetime, attempts: int, retry_after: str | None) -> datetime:
    """Honor a parsed provider reset. Otherwise wait out the backoff.

    The first block (``attempts == 0``) uses ``retry_after`` even when that
    timestamp is already due. A later block reuses it only while it is still
    in the future, so a consumed window cannot relaunch on every tick.
    """
    if retry_after:
        try:
            parsed = parse_time(retry_after)
        except ValueError:
            parsed = None
        if parsed is not None and (attempts <= 0 or parsed > now):
            return parsed
    return now + timedelta(seconds=backoff_seconds(attempts))


def retry_after_of(state: RunState) -> str | None:
    fingerprint = state.failure_fingerprint or {}
    value = fingerprint.get("retry_after") if isinstance(fingerprint, dict) else None
    return str(value) if value else None


def probe_ledger_path(repo_root: Path) -> Path:
    return repo_root / "runtime" / "dispatch" / "condition_probes.json"


def alert_path(repo_root: Path) -> Path:
    return repo_root / "runtime" / "dispatch" / "builder_condition_alerts.json"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def probe_codex_login(*, runner: Callable[..., Any] | None = None) -> bool:
    """Return whether ``codex login status`` exits 0. Never uses a shell."""
    executable = resolve_executable("codex")
    if not executable:
        return False
    from orchestrator.process_ownership import owned_run
    run = runner or owned_run
    try:
        completed = run(
            [executable, "login", "status"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return int(getattr(completed, "returncode", 1) or 0) == 0


def default_builder_probe(blocked_on: str, *, runner: Callable[..., Any] | None = None) -> bool:
    """Quota-free condition probe. Grok always returns false (backoff only)."""
    kind, _, provider = (blocked_on or "").partition(":")
    provider = provider.strip().lower()
    if provider == "grok" or not provider:
        return False
    if provider == "claude":
        from orchestrator.claude_event_consumer import default_condition_probe

        return bool(default_condition_probe(blocked_on))
    if provider == "codex" and kind == "auth":
        return probe_codex_login(runner=runner)
    return False


def consider_probe(repo_root: Path, blocked_on: str, *, now: datetime, probe: Probe) -> bool:
    """Probe at most once per provider per 10 minutes. A true result clears once."""
    provider = provider_of(blocked_on)
    if not provider:
        return False
    path = probe_ledger_path(repo_root)
    ledger = _load_json(path)
    providers = ledger.get("providers")
    if not isinstance(providers, dict):
        providers = {}
    entry = providers.get(provider)
    last = entry.get("last_probe_at") if isinstance(entry, dict) else None
    if last:
        try:
            elapsed = (now - parse_time(str(last))).total_seconds()
        except ValueError:
            elapsed = PROBE_INTERVAL_SECONDS
        if elapsed < PROBE_INTERVAL_SECONDS:
            return False
    providers[provider] = {"last_probe_at": format_time(now)}
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, {"schema_version": "1.0", "providers": providers})
    try:
        return bool(probe(blocked_on))
    except Exception:
        return False


def record_escalation(repo_root: Path, state: RunState) -> None:
    path = alert_path(repo_root)
    current = _load_json(path)
    rows = [row for row in current.get("escalations") or [] if isinstance(row, dict)]
    if not any(row.get("run_id") == state.run_id for row in rows):
        rows.append(
            {
                "run_id": state.run_id,
                "assignment_id": state.assignment_id,
                "blocked_on": state.blocked_on,
                "attempts": state.attempts,
                "escalated_at": state.escalated_at,
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        path,
        {"schema_version": "1.0", "condition_escalation_active": True, "escalations": rows},
    )


def escalate_condition_block(repo_root: Path, state: RunState, *, now: datetime) -> None:
    if state.escalated_at:
        return
    state.process_state = STATE_BLOCKED_EXTERNAL
    state.retry_eligible = False
    state.next_eligible_at = None
    state.escalated_at = format_time(now)
    state.blocked_reason = (
        f"condition retry cap exhausted ({state.attempts}) for {state.blocked_on or 'unknown'}"
    )
    record_escalation(repo_root, state)


def apply_block_schedule(
    repo_root: Path,
    state: RunState,
    *,
    retry_after: str | None,
    now: datetime,
    max_attempts: int,
) -> str:
    """Stamp a fresh eligibility window, or escalate when the cap is already spent."""
    if state.process_state not in CONDITION_STATES or state.escalated_at:
        return "ignored"
    if not state.blocked_on:
        state.blocked_on = blocked_on_for(state.process_state, state.assigned_agent)
    if not state.blocked_since:
        state.blocked_since = format_time(now)
    if state.attempts >= max_attempts:
        escalate_condition_block(repo_root, state, now=now)
        return "escalated"
    state.next_eligible_at = format_time(schedule_next_eligible(now, state.attempts, retry_after))
    return "scheduled"


def maybe_record_recovery(state: RunState, *, now: datetime) -> None:
    """Measure blocked_since -> first genuine activity of a condition relaunch."""
    if state.recovered_at or not state.condition_retry_from_run_id:
        return
    if int(state.activity_events or 0) <= 0:
        return
    state.recovered_at = format_time(now)
    if not state.blocked_since:
        return
    try:
        delta = (now - parse_time(state.blocked_since)).total_seconds()
    except ValueError:
        return
    state.recovery_seconds = max(0, int(delta))


def latest_condition_runs(repo_root: Path) -> list[RunState]:
    seen: set[str] = set()
    chosen: list[RunState] = []
    for state in list_supervisor_runs(repo_root, limit=500):
        if state.assignment_id in seen:
            continue
        seen.add(state.assignment_id)
        if state.process_state not in CONDITION_STATES or not state.blocked_on or state.escalated_at:
            continue
        chosen.append(state)
    return chosen


def evaluate_run(
    repo_root: Path,
    state: RunState,
    *,
    now: datetime,
    probe: Probe,
    max_attempts: int,
) -> str:
    if state.condition_retry_dispatched_at:
        return "waiting"
    if state.escalated_at or state.attempts >= max_attempts:
        return "escalate"
    due: datetime | None = None
    if state.next_eligible_at:
        try:
            due = parse_time(state.next_eligible_at)
        except ValueError:
            due = None
    if due is None and state.blocked_since:
        try:
            due = schedule_next_eligible(parse_time(state.blocked_since), state.attempts, retry_after_of(state))
        except ValueError:
            due = None
    if due is not None and now >= due:
        return "eligible"
    if consider_probe(repo_root, state.blocked_on, now=now, probe=probe):
        return "eligible"
    return "waiting"


def _rollback_dispatch(repo_root: Path, source: RunState, *, now: datetime) -> None:
    logical = source.logical_task_id
    try:
        locks = lock_status(repo_root, logical) if logical else []
    except WorkLockError:
        return
    if locks and locks[0].get("run_id") not in {source.run_id, ""}:
        return
    source.condition_retry_dispatched_at = None
    source.attempts = max(0, int(source.attempts) - 1)
    source.next_eligible_at = format_time(schedule_next_eligible(now, source.attempts, retry_after_of(source)))
    try:
        save_run_state(repo_root, source)
        set_assignment_status(repo_root, source.assignment_id, "reviewable_failure", sync_task_yaml=False)
    except (OSError, WorkLockError, TypeError):
        return


def dispatch_condition_retry(repo_root: Path, source: RunState, *, config: object, launch: Callable[..., dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    """Relaunch once on the preserved worktree, branch, and work lock."""
    now = clock_from(config)
    source.attempts = int(source.attempts) + 1
    source.condition_retry_dispatched_at = format_time(now)
    source.next_eligible_at = format_time(
        schedule_next_eligible(now, source.attempts, retry_after_of(source))
    )
    save_run_state(repo_root, source)
    set_assignment_status(repo_root, source.assignment_id, "building")
    record, _ = read_assignment(repo_root, source.assignment_id)
    task_path = (record.task_path if record is not None else "") or f"tasks/active/{source.task_id}.yaml"
    signal_path = repo_root / "runtime" / "dispatch" / "condition_retry_wake" / f"{source.run_id}.json"
    signal_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        signal_path,
        {
            "schema_version": "1.0",
            "assignment_id": source.assignment_id,
            "task_id": source.task_id,
            "agent_id": source.assigned_agent,
            "adapter_id": source.adapter,
            "task_path": task_path,
            "mechanism": "condition_retry",
            "requested_by": "supervisor",
        },
    )
    report = launch(
        repo_root,
        signal_path,
        config=config,
        condition_retry_from=source,
        **kwargs,
    )
    if report.get("status") in {"error", "deferred"}:
        _rollback_dispatch(repo_root, source, now=now)
        if report.get("status") == "deferred":
            source.next_eligible_at = format_time(now + timedelta(seconds=10))
            save_run_state(repo_root, source)
    return report


def reevaluate_blocked_builders(
    repo_root: Path,
    *,
    config: object,
    launch: Callable[..., dict[str, Any]],
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Periodic tick. Returns None when no blocked builder becomes eligible."""
    now = clock_from(config)
    probe = getattr(config, "condition_probe", None) or default_builder_probe
    max_attempts = int(getattr(config, "max_condition_retries", None) or MAX_CONDITION_RETRIES)
    escalated: list[str] = []
    eligible: list[RunState] = []
    states = latest_condition_runs(repo_root)
    cleared = probe_blocked_providers(
        repo_root, [s for s in states if s.attempts < max_attempts], now=now
    )
    for state in states:
        if (state.blocked_on == f"quota:{provider_of(state.blocked_on)}"
                and provider_of(state.blocked_on) in cleared
                and not state.condition_retry_dispatched_at and state.attempts < max_attempts):
            # Persist all beneficiaries before dispatching one. Later ticks (and
            # restarts) can dispatch the others without buying another probe.
            state.next_eligible_at = format_time(now)
            save_run_state(repo_root, state)
        decision = evaluate_run(repo_root, state, now=now, probe=probe, max_attempts=max_attempts)
        if decision == "escalate":
            escalate_condition_block(repo_root, state, now=now)
            save_run_state(repo_root, state)
            escalated.append(state.run_id)
        elif decision == "eligible":
            eligible.append(state)
    if eligible:
        report = dispatch_condition_retry(repo_root, eligible[0], config=config, launch=launch, **kwargs)
        if escalated:
            report = {**report, "escalated_run_ids": escalated}
        return report
    if escalated:
        return {"status": "condition_escalated", "escalated_run_ids": escalated, "run_id": escalated[0]}
    return None
