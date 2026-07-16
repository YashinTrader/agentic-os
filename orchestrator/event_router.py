"""Route completed physical launches to awaiting_review and Claude-only pokes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dispatch.assignment_channel import complete_assignment, set_assignment_status
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
    """Move assignment to awaiting_review (or blocked) and poke orchestrator only."""
    errors: list[str] = []
    result: dict[str, Any] = {
        "assignment_id": state.assignment_id,
        "run_id": state.run_id,
        "process_state": state.process_state,
        "poke": None,
        "outbox_status": None,
    }

    if state.process_state == STATE_COMPLETED:
        outbox_status = "awaiting_review"
        event = "assignment_completed"
        blocked = None
        out, complete_errors = complete_assignment(
            repo_root,
            state.assignment_id,
            handoff_path=state.handoff_path or None,
            branch_name=branch or state.branch or None,
            branch_tip_sha=branch_tip_sha,
            result_summary=summary or f"physical launch completed run_id={state.run_id}",
            outbox_status=outbox_status,
        )
        errors.extend(complete_errors)
        result["outbox_status"] = outbox_status
        result["outbox"] = out.status if out else None
    elif state.process_state in BLOCKED_EXTERNAL_STATES:
        outbox_status = "blocked"
        event = "assignment_blocked_external"
        blocked = [state.blocked_reason or state.process_state]
        # Keep assignment claimed/building but write blocked outbox via complete with blocked status
        # when still claimable; otherwise set status and poke.
        out, complete_errors = complete_assignment(
            repo_root,
            state.assignment_id,
            handoff_path=state.handoff_path or None,
            branch_name=branch or state.branch or None,
            branch_tip_sha=branch_tip_sha,
            result_summary=summary or f"blocked_external: {state.process_state}",
            blocked_reasons=blocked,
            outbox_status="blocked",
        )
        errors.extend(complete_errors)
        if out is None:
            # Fallback: mark building stays, still poke.
            set_assignment_status(repo_root, state.assignment_id, "building")
        result["outbox_status"] = "blocked"
        result["outbox"] = out.status if out else None
    else:
        outbox_status = "failed"
        event = "assignment_failed"
        blocked = [state.blocked_reason or state.process_state]
        out, complete_errors = complete_assignment(
            repo_root,
            state.assignment_id,
            handoff_path=state.handoff_path or None,
            branch_name=branch or state.branch or None,
            branch_tip_sha=branch_tip_sha,
            result_summary=summary or f"physical launch failed: {state.process_state}",
            blocked_reasons=blocked,
            outbox_status="failed",
        )
        errors.extend(complete_errors)
        result["outbox_status"] = "failed"
        result["outbox"] = out.status if out else None

    # Topology: poke ONLY orchestrator/claude — never peer builders.
    poke, poke_errors = write_orchestrator_poke(
        repo_root,
        source=source if source in {"composer", "grok", "codex", "claude"} else "composer",
        assignment_id=state.assignment_id,
        task_id=state.task_id,
        event=event,
        target="orchestrator",
    )
    errors.extend(poke_errors)
    result["poke"] = poke
    return result, errors


def assert_claude_only_poke_target(target: str) -> None:
    if target not in {"orchestrator", "claude"}:
        raise ValueError("poke target must be orchestrator/claude only")
