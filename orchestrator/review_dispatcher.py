"""Dispatch headless Claude reviews for awaiting_review assignments.

Creates idempotent review requests, launches ClaudeReviewerAdapter, validates
verdicts, and applies resolution via assignment_channel (deterministic).
"""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from dispatch.assignment_channel import (
    list_inbox_assignments,
    read_assignment,
    read_outbox_result,
    resolve_assignment,
    write_assignment,
)
from dispatch.atomic_io import atomic_create_json, atomic_write_json
from dispatch.orchestrator_pokes import write_orchestrator_poke
from orchestrator.claude_reviewer_adapter import (
    AUTH_MODE_LOCAL,
    STATE_BLOCKED_AUTH,
    STATE_BLOCKED_CAPACITY,
    STATE_BLOCKED_NO_ADAPTER,
    STATE_BLOCKED_QUOTA,
    STATE_COMPLETED,
    STATE_INVALID_OUTPUT,
    STATE_QUEUED,
    STATE_RUNNING,
    STATE_TIMED_OUT,
    ClaudeReviewerAdapter,
    ReviewRequest,
    ReviewRunState,
    load_review_state,
    review_run_dir,
    reviews_dir,
    save_review_state,
)
from orchestrator.leases import leases_dir, utc_now
from orchestrator.process_monitor import monitor_process
from orchestrator.review_schema import ReviewVerdict, validate_review_payload
from orchestrator.runtime_store import RunState

DEFAULT_REVIEW_CONCURRENCY = 1


def review_requests_dir(repo_root: Path) -> Path:
    return repo_root / "runtime" / "dispatch" / "review_requests"


def review_lease_path(repo_root: Path, assignment_id: str) -> Path:
    return leases_dir(repo_root) / f"review-{assignment_id}.json"


def review_request_path(repo_root: Path, assignment_id: str) -> Path:
    return review_requests_dir(repo_root) / f"{assignment_id}.json"


def count_active_review_leases(repo_root: Path) -> int:
    root = leases_dir(repo_root)
    if not root.is_dir():
        return 0
    return sum(1 for p in root.glob("review-*.json") if p.is_file())


def try_acquire_review_lease(
    repo_root: Path,
    *,
    assignment_id: str,
    review_run_id: str,
    max_concurrency: int = DEFAULT_REVIEW_CONCURRENCY,
) -> tuple[bool, str]:
    if max_concurrency < 1:
        return False, "review concurrency must be >= 1"
    if count_active_review_leases(repo_root) >= max_concurrency:
        return False, STATE_BLOCKED_CAPACITY + ": review concurrency reached"
    path = review_lease_path(repo_root, assignment_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "assignment_id": assignment_id,
        "review_run_id": review_run_id,
        "holder": "claude-reviewer",
        "acquired_at": utc_now(),
    }
    try:
        atomic_create_json(path, payload)
    except FileExistsError:
        return False, f"review lease already held for {assignment_id}"
    except OSError as exc:
        return False, str(exc)
    return True, "acquired"


def release_review_lease(repo_root: Path, assignment_id: str) -> None:
    path = review_lease_path(repo_root, assignment_id)
    if path.exists():
        path.unlink()


def _git(repo_root: Path, args: list[str]) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            shell=False,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def build_context_bundle(repo_root: Path, assignment_id: str) -> dict[str, Any]:
    record, _ = read_assignment(repo_root, assignment_id)
    outbox, _ = read_outbox_result(repo_root, assignment_id)
    if record is None:
        return {"error": "assignment not found", "assignment_id": assignment_id}

    branch = (outbox.branch_name if outbox else None) or record.new_branch
    local_sha = (outbox.branch_tip_sha if outbox else None) or _git(repo_root, ["rev-parse", "HEAD"])
    remote_sha = _git(repo_root, ["rev-parse", f"origin/{branch}"]) if branch else ""
    if not remote_sha and branch:
        remote_sha = _git(repo_root, ["ls-remote", "origin", branch]).split()[0] if _git(repo_root, ["ls-remote", "origin", branch]) else ""

    changed = []
    if record.base_sha and local_sha:
        diff = _git(repo_root, ["diff", "--name-only", f"{record.base_sha}..{local_sha}"])
        changed = [line for line in diff.splitlines() if line.strip()]

    return {
        "assignment_id": record.assignment_id,
        "task_id": record.task_id,
        "title": record.title,
        "goal": record.goal,
        "acceptance_criteria": list(record.acceptance_criteria or []),
        "base_branch": record.base_branch,
        "base_sha": record.base_sha,
        "implementation_branch": branch,
        "implementation_sha": local_sha,
        "remote_branch": f"origin/{branch}" if branch else "",
        "remote_sha": remote_sha,
        "changed_files": changed,
        "handoff_path": (outbox.handoff_path if outbox else None) or record.handoff_path,
        "allowed_paths": list(record.allowed_paths or []),
        "forbidden_operations": list(record.forbidden_operations or []),
        "verification_commands": list(record.verification_commands or []),
        "correction_cycle_count": 1 if record.correction_note else 0,
        "prior_review_findings": record.resolution_note or record.correction_note,
        "assignment_status": record.status,
        "outbox_status": outbox.status if outbox else None,
        "result_summary": outbox.result_summary if outbox else None,
        "note": "Builder summary is context, not proof. Inspect the repository.",
    }


def create_review_request(repo_root: Path, assignment_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Idempotent: one undrained review request per assignment."""
    path = review_request_path(repo_root, assignment_id)
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            existing["idempotent_replay"] = True
            return existing, []
        except (OSError, json.JSONDecodeError):
            pass

    record, errors = read_assignment(repo_root, assignment_id)
    if record is None:
        return None, errors or ["assignment missing"]
    if record.status != "awaiting_review":
        return None, [f"assignment status {record.status!r} is not awaiting_review"]

    outbox, _ = read_outbox_result(repo_root, assignment_id)
    handoff = ((outbox.handoff_path if outbox else None) or record.handoff_path or "").strip()
    if not handoff:
        return None, ["handoff path missing"]
    branch = ((outbox.branch_name if outbox else None) or record.new_branch or "").strip()
    sha = ((outbox.branch_tip_sha if outbox else None) or "").strip()
    if not sha:
        # Fall back to current HEAD when outbox omitted tip (still require branch).
        sha = _git(repo_root, ["rev-parse", "HEAD"])
    if not branch or not sha:
        return None, ["branch and SHA required for review"]

    review_run_id = f"review-{utc_now().replace(':', '')}-{uuid.uuid4().hex[:8]}"
    bundle = build_context_bundle(repo_root, assignment_id)
    run_dir = review_run_dir(repo_root, review_run_id)
    bundle_path = run_dir / "context_bundle.json"
    bundle_path.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")

    payload = {
        "schema_version": "1.0",
        "event": "review.requested",
        "assignment_id": assignment_id,
        "task_id": record.task_id,
        "review_run_id": review_run_id,
        "branch": branch,
        "local_sha": sha,
        "remote_sha": bundle.get("remote_sha") or sha,
        "handoff_path": handoff,
        "base_branch": record.base_branch,
        "base_sha": record.base_sha,
        "context_bundle_path": bundle_path.relative_to(repo_root).as_posix(),
        "created_at": utc_now(),
        "status": "queued",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        atomic_create_json(path, payload)
    except FileExistsError:
        existing = json.loads(path.read_text(encoding="utf-8"))
        existing["idempotent_replay"] = True
        return existing, []
    return payload, []


def list_awaiting_review(repo_root: Path) -> list[str]:
    records, _ = list_inbox_assignments(repo_root)
    return [r.assignment_id for r in records if r.status == "awaiting_review"]


def apply_verdict(
    repo_root: Path,
    *,
    assignment_id: str,
    verdict: ReviewVerdict,
    reviewed_by: str = "claude",
    wake_composer: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    """Transactionally apply a validated Claude verdict via assignment_channel only."""
    errors: list[str] = []
    result: dict[str, Any] = {
        "assignment_id": assignment_id,
        "verdict": verdict.verdict,
        "resolution": None,
        "correction_assignment_id": None,
        "wake": None,
    }

    note = verdict.summary
    if verdict.required_changes:
        note = note + "\n\nRequired changes:\n- " + "\n- ".join(verdict.required_changes)

    record, resolve_errors = resolve_assignment(
        repo_root,
        assignment_id,
        resolution=verdict.verdict,  # type: ignore[arg-type]
        note=note,
        reviewed_by=reviewed_by,
        sync_task_yaml=True,
    )
    errors.extend(resolve_errors)
    if record is None:
        return result, errors
    result["resolution"] = record.status

    write_orchestrator_poke(
        repo_root,
        source="claude",
        assignment_id=assignment_id,
        task_id=record.task_id,
        event=f"review_resolved_{verdict.verdict}",
        target="orchestrator",
    )

    if verdict.verdict == "changes_requested" and wake_composer:
        # Re-claimable original stays; also ensure wake queue for composer.
        from dispatch.agent_wake import request_agent_wake

        try:
            wake = request_agent_wake(
                repo_root,
                assignment_id=assignment_id,
                task_id=record.task_id,
                agent_id=record.assigned_to or "composer",
                adapter_id=record.adapter_id or "composer-restricted",
                task_path=record.task_path or "",
                requested_by="claude",
            )
            result["wake"] = wake.to_dict() if hasattr(wake, "to_dict") else {
                "state": wake.state,
                "delivered": wake.delivered,
                "detail": wake.detail,
            }
        except (OSError, ValueError) as exc:
            # Fallback: write wake queue file directly so physical supervisor can pick up.
            queue = repo_root / "runtime" / "dispatch" / "wake_queue" / (record.assigned_to or "composer")
            queue.mkdir(parents=True, exist_ok=True)
            wake_payload = {
                "schema_version": "1.0",
                "assignment_id": assignment_id,
                "task_id": record.task_id,
                "agent_id": record.assigned_to or "composer",
                "adapter_id": record.adapter_id or "composer-restricted",
                "task_path": record.task_path or "",
                "mechanism": "physical_supervisor",
                "requested_by": "claude",
                "requested_at": utc_now(),
                "fallback_reason": str(exc),
            }
            wake_path = queue / f"{assignment_id}.json"
            atomic_write_json(wake_path, wake_payload)
            result["wake"] = {
                "state": "wake_delivered",
                "delivered": True,
                "detail": "fallback wake queue write",
                "signal_path": wake_path.relative_to(repo_root).as_posix(),
            }

    if verdict.next_assignment.get("required") and verdict.verdict == "accepted":
        na = verdict.next_assignment
        path, create_errors = write_assignment(
            repo_root,
            task_id=str(na.get("task_id") or f"T-FOLLOWUP-{record.task_id}"),
            title=str(na.get("goal") or "Follow-up task")[:120],
            goal=str(na.get("goal") or ""),
            base_branch=record.new_branch or record.base_branch,
            base_sha=record.base_sha,
            allowed_paths=list(record.allowed_paths or []),
            forbidden_operations=list(record.forbidden_operations or []),
            acceptance_criteria=["follow-up complete"],
            verification_commands=list(record.verification_commands or ["python scripts/validate.py"]),
            assigned_by="claude",
            assigned_to=str(na.get("assigned_to") or "composer"),
            wake=True,
            task_path=record.task_path or "",
            instructions=f"Created by Claude reviewer after accepting {assignment_id}",
        )
        errors.extend(create_errors)
        if path is not None:
            result["next_assignment_id"] = path.stem

    return result, errors


def process_one_review(
    repo_root: Path,
    *,
    assignment_id: str | None = None,
    adapter: ClaudeReviewerAdapter | None = None,
    review_concurrency: int = DEFAULT_REVIEW_CONCURRENCY,
    timeout_seconds: int = 1800,
    activity_timeout_seconds: int = 90,
    monitor: Callable[..., Any] | None = None,
    apply: bool = True,
) -> dict[str, Any]:
    """Pick one awaiting_review assignment, run Claude review, optionally apply verdict."""
    targets = [assignment_id] if assignment_id else list_awaiting_review(repo_root)
    if not targets:
        return {"status": "idle", "reason": "no awaiting_review assignments"}

    aid = targets[0]
    request_payload, req_errors = create_review_request(repo_root, aid)
    if request_payload is None:
        return {"status": "error", "assignment_id": aid, "errors": req_errors}

    # Skip if already finalized review exists with completed verdict.
    existing_run = request_payload.get("review_run_id")
    if existing_run:
        prior = load_review_state(repo_root, str(existing_run))
        if prior and prior.process_state == STATE_COMPLETED and prior.verdict and request_payload.get("status") == "applied":
            return {
                "status": "completed",
                "reason": "review already applied",
                "assignment_id": aid,
                "review_run_id": existing_run,
                "pid": prior.pid,
                "session_id": prior.session_id,
                "verdict": prior.verdict.get("verdict"),
                "recovered": True,
            }

    review_run_id = str(request_payload["review_run_id"])
    ok, lease_reason = try_acquire_review_lease(
        repo_root, assignment_id=aid, review_run_id=review_run_id, max_concurrency=review_concurrency
    )
    if not ok:
        return {"status": "deferred", "reason": lease_reason, "assignment_id": aid}

    try:
        record, _ = read_assignment(repo_root, aid)
        assert record is not None
        req = ReviewRequest(
            assignment_id=aid,
            task_id=record.task_id,
            branch=str(request_payload["branch"]),
            local_sha=str(request_payload["local_sha"]),
            remote_sha=str(request_payload.get("remote_sha") or request_payload["local_sha"]),
            handoff_path=str(request_payload["handoff_path"]),
            base_branch=str(request_payload.get("base_branch") or ""),
            base_sha=str(request_payload.get("base_sha") or ""),
            context_bundle_path=str(
                repo_root / request_payload["context_bundle_path"]
                if not Path(str(request_payload["context_bundle_path"])).is_absolute()
                else request_payload["context_bundle_path"]
            ),
            prompt_path=str(review_run_dir(repo_root, review_run_id) / "prompt.txt"),
            review_run_id=review_run_id,
            timeout_seconds=timeout_seconds,
            cwd=str(repo_root),
        )
        reviewer = adapter or ClaudeReviewerAdapter(repo_root, auth_mode=AUTH_MODE_LOCAL)
        state = reviewer.launch_review(req)
        if state.process_state != STATE_RUNNING:
            request_payload["status"] = state.process_state
            request_payload["blocked_reason"] = state.blocked_reason
            atomic_write_json(review_request_path(repo_root, aid), request_payload)
            # Leave assignment in awaiting_review on reviewer failure.
            return {
                "status": state.process_state,
                "assignment_id": aid,
                "review_run_id": review_run_id,
                "pid": state.pid,
                "blocked_reason": state.blocked_reason,
                "assignment_status": "awaiting_review",
            }

        handle = reviewer._handles.get(review_run_id)
        if handle is not None and monitor is not None:
            # Custom monitor path (tests)
            mon = monitor(
                handle.process,
                state=RunState(
                    run_id=review_run_id,
                    assignment_id=aid,
                    task_id=record.task_id,
                    assigned_agent="claude",
                    adapter="claude-reviewer",
                    process_state="running",
                    pid=handle.pid,
                ),
                repo_root=repo_root,
                stdout_path=repo_root / state.stdout_path,
                stderr_path=repo_root / state.stderr_path,
                timeout_seconds=timeout_seconds,
            )
            # Force poll after monitor
            if mon.timed_out:
                reviewer.cancel_review(review_run_id)
                state = load_review_state(repo_root, review_run_id) or state
                state.process_state = STATE_TIMED_OUT
                state.blocked_reason = "timed out"
                save_review_state(repo_root, state)
            else:
                # Write mon stdout/stderr already captured; re-poll
                state = reviewer.poll_review(review_run_id)
        elif handle is not None:
            # Observe stream-json incrementally; process exit also permits parsing a
            # buffered final result before classifying launch activity.
            activity_started = time.monotonic()
            while handle.process.poll() is None:
                try:
                    if (repo_root / state.stdout_path).stat().st_size > 0:
                        break
                except OSError:
                    pass
                if time.monotonic() - activity_started >= activity_timeout_seconds:
                    reviewer.cancel_review(review_run_id)
                    state = load_review_state(repo_root, review_run_id) or state
                    state.process_state = "failed_launch"
                    state.blocked_reason = "genuine activity watchdog expired"
                    save_review_state(repo_root, state)
                    request_payload["status"] = "failed_launch"
                    request_payload["blocked_reason"] = state.blocked_reason
                    atomic_write_json(review_request_path(repo_root, aid), request_payload)
                    return {
                        "status": "failed_launch", "assignment_id": aid,
                        "review_run_id": review_run_id, "pid": state.pid,
                        "blocked_reason": state.blocked_reason,
                        "assignment_status": "awaiting_review",
                    }
                time.sleep(0.1)
            elapsed = time.monotonic() - activity_started
            try:
                code = handle.process.wait(timeout=max(0.1, timeout_seconds - elapsed))
            except Exception:
                reviewer.cancel_review(review_run_id)
                state = load_review_state(repo_root, review_run_id) or state
                state.process_state = STATE_TIMED_OUT
                state.blocked_reason = "timed out"
                save_review_state(repo_root, state)
                request_payload["status"] = STATE_TIMED_OUT
                atomic_write_json(review_request_path(repo_root, aid), request_payload)
                return {
                    "status": STATE_TIMED_OUT,
                    "assignment_id": aid,
                    "review_run_id": review_run_id,
                    "pid": state.pid,
                    "assignment_status": "awaiting_review",
                }
            del code
            state = reviewer.poll_review(review_run_id)
        else:
            state = reviewer.poll_review(review_run_id)

        if state.process_state != STATE_COMPLETED or not state.verdict:
            request_payload["status"] = state.process_state
            request_payload["blocked_reason"] = state.blocked_reason
            atomic_write_json(review_request_path(repo_root, aid), request_payload)
            return {
                "status": state.process_state or STATE_INVALID_OUTPUT,
                "assignment_id": aid,
                "review_run_id": review_run_id,
                "pid": state.pid,
                "session_id": state.session_id,
                "blocked_reason": state.blocked_reason,
                "assignment_status": "awaiting_review",
            }

        verdict, v_errors = validate_review_payload(state.verdict)
        if verdict is None:
            request_payload["status"] = STATE_INVALID_OUTPUT
            request_payload["blocked_reason"] = "; ".join(v_errors)
            atomic_write_json(review_request_path(repo_root, aid), request_payload)
            return {
                "status": STATE_INVALID_OUTPUT,
                "assignment_id": aid,
                "review_run_id": review_run_id,
                "errors": v_errors,
                "assignment_status": "awaiting_review",
            }

        applied: dict[str, Any] = {}
        apply_errors: list[str] = []
        if apply:
            applied, apply_errors = apply_verdict(repo_root, assignment_id=aid, verdict=verdict)
            request_payload["status"] = "applied"
            request_payload["verdict"] = verdict.verdict
            request_payload["applied_at"] = utc_now()
        else:
            request_payload["status"] = "completed_unapplied"
            request_payload["verdict"] = verdict.verdict
        atomic_write_json(review_request_path(repo_root, aid), request_payload)

        return {
            "status": "completed",
            "assignment_id": aid,
            "review_run_id": review_run_id,
            "pid": state.pid,
            "session_id": state.session_id,
            "verdict": verdict.verdict,
            "applied": applied,
            "apply_errors": apply_errors,
        }
    finally:
        release_review_lease(repo_root, aid)


@dataclass
class ReviewDispatcherConfig:
    review_concurrency: int = DEFAULT_REVIEW_CONCURRENCY
    timeout_seconds: int = 1800
    auth_mode: str = AUTH_MODE_LOCAL
    claude_executable: str | None = None
    apply_verdicts: bool = True
