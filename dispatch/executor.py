"""Phase 3.2 controlled executor — operator-commanded, gate-gated, timeout-bounded."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dispatch.approval_replay import try_claim_approval
from dispatch.approval_store import load_approval_record
from dispatch.worktree_registry import (
    allocation_record_to_dict,
    load_allocation_record,
)
from dispatch.execution_gate import evaluate_execution_gates
from dispatch.executor_contract import (
    build_execution_request_from_preview,
    execution_request_to_dict,
    load_cli_inventory,
    resolve_adapter_for_request,
)
from dispatch.preview import command_tokens, utc_now
from dispatch.runtime_capture import (
    ExecutionResult,
    append_run_event,
    persist_latest_pointers,
    run_directory,
    write_approval_copy,
    write_execution_request,
    write_handoff_required_md,
    write_preview_copy,
    write_result,
    write_rollback_md,
)


def _emit_dispatch_event(
    repo_root: Path,
    event_type: str,
    *,
    task_id: str,
    run_id: str,
    detail: str,
    ref: str = "",
    run_dir: Path | None = None,
    event_emit_errors: list[str] | None = None,
) -> None:
    errors = event_emit_errors if event_emit_errors is not None else []
    try:
        from protocol.emit_event import append_event

        append_event(
            repo_root,
            agent="dispatch-executor",
            event_type=event_type,
            task_id=task_id,
            detail=detail,
            ref=ref,
        )
    except Exception as exc:
        msg = f"central agent-events emit failed for {event_type}: {exc}"
        errors.append(msg)
        if run_dir is not None:
            try:
                append_run_event(
                    run_dir,
                    {
                        "ts": utc_now(),
                        "type": "event_emit_error",
                        "task_id": task_id,
                        "detail": msg,
                        "ref": ref,
                    },
                )
            except Exception as nested:
                errors.append(f"failed to record event_emit_error locally: {nested}")


def load_preview(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("preview must be a JSON object")
    return data


def execute_dispatch(
    repo_root: Path,
    preview_path: Path,
    *,
    operator_execute: bool = False,
    dry_run: bool = False,
    approval_path: Path | None = None,
    worktree_root: str | None = None,
    allocation_path: Path | None = None,
    allocation_id: str | None = None,
) -> ExecutionResult:
    """
    Controlled dispatch executor. Subprocess runs only when:
    operator_execute=True, dry_run=False, and all gates pass.
    """
    repo_root = repo_root.resolve()
    event_emit_errors: list[str] = []
    preview = load_preview(preview_path)
    run_id = str(preview.get("run_id", ""))
    task_id = str(preview.get("task_id", ""))
    adapter_id = str(preview.get("adapter_id", ""))

    adapter = resolve_adapter_for_request(repo_root, adapter_id)
    cli_inventory = load_cli_inventory(repo_root)

    approval_record: dict[str, Any] | None = None
    if approval_path and approval_path.exists():
        approval_record = load_approval_record(approval_path)

    allocation_record: dict[str, Any] | None = None
    if allocation_path and allocation_path.exists():
        allocation_record = json.loads(allocation_path.read_text(encoding="utf-8"))
    elif allocation_id:
        allocation_record = allocation_record_to_dict(load_allocation_record(repo_root, allocation_id))

    effective_worktree_root = worktree_root
    if allocation_record is not None:
        effective_worktree_root = str(allocation_record.get("worktree_path", worktree_root or ""))

    gate = evaluate_execution_gates(
        repo_root,
        preview,
        adapter=adapter,
        cli_inventory=cli_inventory,
        approval_record=approval_record,
        operator_execute=operator_execute,
        dry_run=dry_run,
        worktree_root=effective_worktree_root,
        allocation_record=allocation_record,
        check_replay=operator_execute and not dry_run,
    )

    run_dir = run_directory(repo_root, run_id)
    write_preview_copy(run_dir, preview)

    approval_record_path = None
    if approval_record is not None:
        write_approval_copy(run_dir, approval_record)
        approval_record_path = str(
            (run_dir / "approval_record.json").relative_to(repo_root)
        )

    request = build_execution_request_from_preview(
        preview,
        approval_record_path=approval_record_path,
        adapter=adapter,
    )
    request_dict = execution_request_to_dict(request)
    request_dict["operator_execute"] = operator_execute
    request_dict["dry_run"] = dry_run
    request_dict["preview_hash"] = gate.preview_hash
    request_dict["gate_blocked_reasons"] = gate.blocked_reasons
    write_execution_request(run_dir, request_dict)

    latest_req = repo_root / "runtime" / "dispatch" / "latest_execution_request.json"
    latest_req.parent.mkdir(parents=True, exist_ok=True)
    latest_req.write_text(json.dumps(request_dict, indent=2, ensure_ascii=False), encoding="utf-8")

    handoff_path = str(preview.get("handoff_path", ""))
    rollback_path = str((run_dir / "rollback.md").relative_to(repo_root))
    write_rollback_md(run_dir, str(preview.get("rollback_strategy", "")))
    write_handoff_required_md(run_dir, handoff_path)

    started_at = utc_now()
    append_run_event(
        run_dir,
        {"ts": started_at, "type": "dispatch_requested", "run_id": run_id, "dry_run": dry_run},
    )

    _emit_dispatch_event(
        repo_root,
        "dispatch_requested",
        task_id=task_id,
        run_id=run_id,
        detail=f"run_id={run_id} dry_run={dry_run} execute={operator_execute}",
        ref=str(run_dir.relative_to(repo_root)),
        run_dir=run_dir,
        event_emit_errors=event_emit_errors,
    )

    if not gate.execution_allowed:
        finished_at = utc_now()
        result = ExecutionResult(
            run_id=run_id,
            task_id=task_id,
            adapter_id=adapter_id,
            executed=False,
            execution_allowed=False,
            approval_level=gate.approval_level,
            approval_status=gate.approval_status,
            started_at=started_at,
            finished_at=finished_at,
            blocked_reasons=gate.blocked_reasons,
            handoff_path=handoff_path,
            rollback_path=rollback_path,
            result_path=str((run_dir / "result.json").relative_to(repo_root)),
        )
        write_result(run_dir, result)
        persist_latest_pointers(repo_root, run_id, result)
        append_run_event(
            run_dir,
            {"ts": finished_at, "type": "dispatch_blocked", "reasons": gate.blocked_reasons},
        )
        _emit_dispatch_event(
            repo_root,
            "dispatch_blocked",
            task_id=task_id,
            run_id=run_id,
            detail="; ".join(gate.blocked_reasons[:5]),
            ref=result.result_path,
            run_dir=run_dir,
            event_emit_errors=event_emit_errors,
        )
        result.event_emit_errors = list(event_emit_errors)
        write_result(run_dir, result)
        return result

    if dry_run:
        finished_at = utc_now()
        result = ExecutionResult(
            run_id=run_id,
            task_id=task_id,
            adapter_id=adapter_id,
            executed=False,
            execution_allowed=True,
            approval_level=gate.approval_level,
            approval_status=gate.approval_status,
            started_at=started_at,
            finished_at=finished_at,
            handoff_path=handoff_path,
            rollback_path=rollback_path,
            result_path=str((run_dir / "result.json").relative_to(repo_root)),
        )
        write_result(run_dir, result)
        persist_latest_pointers(repo_root, run_id, result)
        append_run_event(run_dir, {"ts": finished_at, "type": "dispatch_dry_run_completed"})
        _emit_dispatch_event(
            repo_root,
            "dispatch_dry_run_completed",
            task_id=task_id,
            run_id=run_id,
            detail=f"dry-run gates passed run_id={run_id}",
            ref=result.result_path,
            run_dir=run_dir,
            event_emit_errors=event_emit_errors,
        )
        _emit_dispatch_event(
            repo_root,
            "handoff_required",
            task_id=task_id,
            run_id=run_id,
            detail=f"handoff required at {handoff_path}",
            ref=handoff_path,
            run_dir=run_dir,
            event_emit_errors=event_emit_errors,
        )
        result.event_emit_errors = list(event_emit_errors)
        write_result(run_dir, result)
        return result

    if approval_record is not None and operator_execute and not dry_run:
        claim = try_claim_approval(
            repo_root,
            approval_id=str(approval_record.get("approval_id", "")),
            run_id=run_id,
            task_id=task_id,
            preview_hash=gate.preview_hash,
            execution_request_id=run_id,
        )
        if not claim.claimed:
            finished_at = utc_now()
            reasons = claim.errors or ["approval claim failed"]
            result = ExecutionResult(
                run_id=run_id,
                task_id=task_id,
                adapter_id=adapter_id,
                executed=False,
                execution_allowed=False,
                approval_level=gate.approval_level,
                approval_status="invalid",
                started_at=started_at,
                finished_at=finished_at,
                blocked_reasons=reasons,
                handoff_path=handoff_path,
                rollback_path=rollback_path,
                result_path=str((run_dir / "result.json").relative_to(repo_root)),
            )
            write_result(run_dir, result)
            persist_latest_pointers(repo_root, run_id, result)
            _emit_dispatch_event(
                repo_root,
                "approval_replay_blocked",
                task_id=task_id,
                run_id=run_id,
                detail="; ".join(reasons),
                ref=result.result_path,
                run_dir=run_dir,
                event_emit_errors=event_emit_errors,
            )
            result.event_emit_errors = list(event_emit_errors)
            write_result(run_dir, result)
            return result
        _emit_dispatch_event(
            repo_root,
            "approval_consumed",
            task_id=task_id,
            run_id=run_id,
            detail=f"approval_id={approval_record.get('approval_id')}",
            ref=str(claim.claim_path or ""),
            run_dir=run_dir,
            event_emit_errors=event_emit_errors,
        )

    command = str(preview.get("command", ""))
    cwd = str(preview.get("working_directory", repo_root))
    adapter_writes = bool((adapter or {}).get("writes_files"))
    if effective_worktree_root and adapter_writes:
        cwd = effective_worktree_root
    timeout_seconds = int(preview.get("timeout_seconds") or 300)
    tokens, _ = command_tokens(command)

    append_run_event(run_dir, {"ts": utc_now(), "type": "dispatch_started", "command": command})
    _emit_dispatch_event(
        repo_root,
        "dispatch_started",
        task_id=task_id,
        run_id=run_id,
        detail=f"subprocess start adapter={adapter_id}",
        ref=str(run_dir.relative_to(repo_root)),
        run_dir=run_dir,
        event_emit_errors=event_emit_errors,
    )

    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    exit_code: int | None = None
    timed_out = False
    error: str | None = None
    start_mono = datetime.now(timezone.utc)

    try:
        completed = subprocess.run(
            tokens,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        exit_code = completed.returncode
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = None
        stdout_path.write_text((exc.stdout or b"").decode("utf-8", errors="replace"), encoding="utf-8")
        stderr_path.write_text((exc.stderr or b"").decode("utf-8", errors="replace"), encoding="utf-8")
        error = f"timed out after {timeout_seconds}s"
    except Exception as exc:
        error = str(exc)
        stderr_path.write_text(str(exc) + "\n", encoding="utf-8")

    finished_at = utc_now()
    duration_ms = int((datetime.now(timezone.utc) - start_mono).total_seconds() * 1000)

    event_type = "dispatch_completed"
    if timed_out:
        event_type = "dispatch_timed_out"
    elif exit_code != 0 or error:
        event_type = "dispatch_failed"

    result = ExecutionResult(
        run_id=run_id,
        task_id=task_id,
        adapter_id=adapter_id,
        executed=True,
        execution_allowed=True,
        approval_level=gate.approval_level,
        approval_status=gate.approval_status,
        exit_code=exit_code,
        timed_out=timed_out,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        stdout_path=str(stdout_path.relative_to(repo_root)),
        stderr_path=str(stderr_path.relative_to(repo_root)),
        result_path=str((run_dir / "result.json").relative_to(repo_root)),
        error=error,
        handoff_path=handoff_path,
        rollback_path=rollback_path,
    )
    write_result(run_dir, result)
    persist_latest_pointers(repo_root, run_id, result)
    append_run_event(
        run_dir,
        {
            "ts": finished_at,
            "type": event_type,
            "exit_code": exit_code,
            "timed_out": timed_out,
        },
    )
    _emit_dispatch_event(
        repo_root,
        event_type,
        task_id=task_id,
        run_id=run_id,
        detail=f"exit_code={exit_code} timed_out={timed_out}",
        ref=result.result_path,
        run_dir=run_dir,
        event_emit_errors=event_emit_errors,
    )
    _emit_dispatch_event(
        repo_root,
        "handoff_required",
        task_id=task_id,
        run_id=run_id,
        detail=f"handoff required at {handoff_path}",
        ref=handoff_path,
        run_dir=run_dir,
        event_emit_errors=event_emit_errors,
    )
    result.event_emit_errors = list(event_emit_errors)
    write_result(run_dir, result)
    return result