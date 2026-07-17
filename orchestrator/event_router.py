"""Route completed physical launches to awaiting_review and Claude-only pokes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dispatch.assignment_channel import (
    complete_assignment,
    read_assignment,
    set_assignment_status,
    write_outbox_result,
)
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
        event = None
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
        record, read_errors = read_assignment(repo_root, state.assignment_id)
        errors.extend(read_errors)
        out_path = None
        if record is not None:
            out_path, out_errors = write_outbox_result(
                repo_root, assignment_id=state.assignment_id, task_id=record.task_id,
                adapter_id=record.adapter_id, run_id=state.run_id,
                handoff_path=state.handoff_path or None, branch_name=branch or state.branch or None,
                branch_tip_sha=branch_tip_sha, blocked_reasons=blocked, status="blocked",
                result_summary=summary or f"blocked_external: {state.process_state}",
            )
            errors.extend(out_errors)
            _, status_errors = set_assignment_status(
                repo_root, state.assignment_id, "reviewable_failure", sync_task_yaml=False
            )
            errors.extend(status_errors)
        result["outbox_status"] = "blocked"
        result["outbox"] = "blocked" if out_path else None
    else:
        outbox_status = "failed"
        event = "assignment_failed"
        blocked = [state.blocked_reason or state.process_state]
        record, read_errors = read_assignment(repo_root, state.assignment_id)
        errors.extend(read_errors)
        out_path = None
        if record is not None:
            out_path, out_errors = write_outbox_result(
                repo_root,
                assignment_id=state.assignment_id,
                task_id=record.task_id,
                adapter_id=record.adapter_id,
                run_id=state.run_id,
                claim_path=f"runtime/dispatch/assignments/claims/{state.assignment_id}.json",
                handoff_path=state.handoff_path or None,
                branch_name=branch or state.branch or None,
                branch_tip_sha=branch_tip_sha,
                result_summary=summary or f"physical launch failed: {state.process_state}",
                blocked_reasons=blocked,
                status="failed",
            )
            errors.extend(out_errors)
            _, status_errors = set_assignment_status(
                repo_root, state.assignment_id, "reviewable_failure", sync_task_yaml=False
            )
            errors.extend(status_errors)
        result["outbox_status"] = "failed"
        result["outbox"] = "failed" if out_path else None

    # Topology: poke ONLY orchestrator/claude — never peer builders.
    if event is not None:
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
