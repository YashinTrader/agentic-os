"""Bridge execution outcomes to the assignment completion + notification layers.

Execution layer evidence: PID, run state, stdout/stderr under runtime/dispatch/runs/.
Completion evidence: outbox, handoff path, tests, assignment status awaiting_review.
Notification evidence: structured poke to orchestrator only.

A poke is never a process launch. A process launch is never completion.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dispatch.assignment_channel import complete_assignment, read_assignment, set_assignment_status
from dispatch.orchestrator_pokes import write_orchestrator_poke
from orchestrator.runtime_store import (
    BLOCKED_EXTERNAL_STATES,
    STATE_COMPLETED,
    RunState,
)


def route_completion(
    repo_root: Path,
    state: RunState,
    *,
    branch: str | None = None,
    branch_tip_sha: str | None = None,
    summary: str | None = None,
    source: str = "composer",
) -> tuple[dict[str, Any], list[str]]:
    """After a physical run ends: complete assignment first, then notify Claude.

    Order is mandatory:
      1) write outbox + handoff metadata
      2) transition assignment → awaiting_review
      3) emit idempotent orchestrator poke
    """
    errors: list[str] = []
    result: dict[str, Any] = {
        "assignment_id": state.assignment_id,
        "run_id": state.run_id,
        "process_state": state.process_state,
        "execution_layer": {
            "pid": state.pid,
            "run_id": state.run_id,
            "process_state": state.process_state,
            "stdout_path": state.stdout_path,
            "stderr_path": state.stderr_path,
        },
        "notification_layer": {
            "poke": None,
            "target": "orchestrator",
            "is_process_launch": False,
        },
        "completion_layer": {
            "outbox_status": None,
            "assignment_status": None,
            "handoff_path": state.handoff_path or None,
        },
        "poke": None,
        "outbox_status": None,
    }

    if state.process_state == STATE_COMPLETED:
        outbox_status = "awaiting_review"
        event = "assignment_completed"
        blocked = None
        summary_text = summary or (
            f"completed run_id={state.run_id} pid={state.pid}; "
            "execution evidence is the run record, not the poke"
        )
    elif state.process_state in BLOCKED_EXTERNAL_STATES:
        outbox_status = "blocked"
        event = "assignment_blocked_external"
        blocked = [state.blocked_reason or state.process_state]
        summary_text = summary or f"blocked_external: {state.process_state}"
    else:
        outbox_status = "failed"
        event = "assignment_failed"
        blocked = [state.blocked_reason or state.process_state]
        summary_text = summary or f"physical launch failed: {state.process_state}"

    # Completion transition first (emit_poke=False so we control order + event here).
    out, complete_errors = complete_assignment(
        repo_root,
        state.assignment_id,
        handoff_path=state.handoff_path or None,
        branch_name=branch or state.branch or None,
        branch_tip_sha=branch_tip_sha,
        result_summary=summary_text,
        blocked_reasons=blocked,
        outbox_status=outbox_status,
        emit_poke=False,
    )
    errors.extend(complete_errors)
    if out is None and state.process_state in BLOCKED_EXTERNAL_STATES:
        set_assignment_status(repo_root, state.assignment_id, "building")

    result["outbox_status"] = outbox_status
    result["outbox"] = out.status if out else None
    result["completion_layer"]["outbox_status"] = outbox_status

    rec, read_errors = read_assignment(repo_root, state.assignment_id)
    errors.extend(read_errors)
    assignment_status = rec.status if rec else None
    result["completion_layer"]["assignment_status"] = assignment_status

    # Notification only after awaiting_review (or when completion path succeeded).
    poke = None
    if assignment_status == "awaiting_review":
        poke, poke_errors = write_orchestrator_poke(
            repo_root,
            source=source if source in {"composer", "grok", "codex", "claude"} else "composer",
            assignment_id=state.assignment_id,
            task_id=state.task_id,
            event=event,
            target="orchestrator",
        )
        errors.extend(poke_errors)
    else:
        errors.append(
            f"skipping poke: assignment status is {assignment_status!r}, expected awaiting_review"
        )

    result["poke"] = poke
    result["notification_layer"]["poke"] = poke
    return result, errors


def assert_claude_only_poke_target(target: str) -> None:
    if target not in {"orchestrator", "claude"}:
        raise ValueError("poke target must be orchestrator/claude only")
