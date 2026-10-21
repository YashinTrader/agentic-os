#!/usr/bin/env python3
"""Operator-started local builder worker — polls auto_local_worktree tasks."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch import work_lock
from dispatch.atomic_io import atomic_create_json  # noqa: E402
from dispatch.codex_local_builder import run_local_builder  # noqa: E402
from dispatch.codex_local_builder_gate import evaluate_worker_task_eligibility  # noqa: E402
from dispatch.execution_policy import load_execution_policy  # noqa: E402
from orchestrator.loaders import load_task_yaml  # noqa: E402

CLAIM_DIR_NAME = "local_builder_claims"
STOP_REQUESTED = False


def _claim_dir(repo_root: Path) -> Path:
    return repo_root / "runtime" / "dispatch" / CLAIM_DIR_NAME


def _active_claims(repo_root: Path) -> list[Path]:
    directory = _claim_dir(repo_root)
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.json"))


def _count_active_runs(repo_root: Path) -> int:
    return len(_active_claims(repo_root))


def _eligible_tasks(repo_root: Path) -> list[Path]:
    tasks_dir = repo_root / "tasks" / "active"
    eligible: list[Path] = []
    for path in sorted(tasks_dir.glob("*.yaml")):
        try:
            task = load_task_yaml(path)
        except (OSError, ValueError, yaml.YAMLError):
            continue
        task_id = str(task.get("id", path.stem))
        has_claim = (_claim_dir(repo_root) / f"{task_id}.json").exists()
        ok, _ = evaluate_worker_task_eligibility(repo_root, task, has_active_claim=has_claim)
        if ok:
            eligible.append(path)
    return eligible


def try_claim_task(repo_root: Path, task_id: str, run_id: str) -> bool:
    claim_dir = _claim_dir(repo_root)
    claim_dir.mkdir(parents=True, exist_ok=True)
    claim_path = claim_dir / f"{task_id}.json"
    try:
        atomic_create_json(
            claim_path,
            {"task_id": task_id, "run_id": run_id, "claimed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        )
        return True
    except FileExistsError:
        return False


def release_claim(repo_root: Path, task_id: str) -> None:
    claim_path = _claim_dir(repo_root) / f"{task_id}.json"
    if claim_path.exists():
        claim_path.unlink()


def _handle_stop(signum: int, frame: object) -> None:
    del signum, frame
    global STOP_REQUESTED
    STOP_REQUESTED = True


def process_one(repo_root: Path, *, task_path: Path | None = None) -> dict:
    policy = load_execution_policy(repo_root)
    max_concurrent = int(policy.get("maximum_concurrent_runs", 1) or 1)
    guard_error = work_lock.concurrency_error(repo_root, max_concurrent)
    if guard_error:
        return {"status": "skipped", "reason": guard_error}
    if _count_active_runs(repo_root) >= max_concurrent:
        return {"status": "skipped", "reason": "maximum concurrent runs reached"}

    if task_path is None:
        eligible = _eligible_tasks(repo_root)
        if not eligible:
            return {"status": "idle", "reason": "no eligible tasks"}
        task_path = eligible[0]

    task = load_task_yaml(task_path)
    task_id = str(task.get("id", task_path.stem))

    from dispatch.codex_local_builder import generate_run_id

    run_id = generate_run_id(task_id)
    if not try_claim_task(repo_root, task_id, run_id):
        return {"status": "skipped", "reason": f"task {task_id} already claimed"}

    assignment_id = ""
    try:
        logical_id = work_lock.logical_id_for_task(repo_root, task)
        try:
            existing = work_lock.status(repo_root, logical_id)
            if existing and existing[0]['holder_agent'] == 'codex' and existing[0]['state'] == 'reserved' and existing[0]['assignment_id']:
                from dispatch.assignment_channel import claim_assignment, read_assignment
                assignment_id = existing[0]['assignment_id']
                record, errors = read_assignment(repo_root, assignment_id)
                if record is None or record.task_id != task_id:
                    raise work_lock.WorkLockError('; '.join(errors) or f'assignment task mismatch; holder {existing[0]["holder_agent"]} ({assignment_id})')
                record, errors = claim_assignment(repo_root, assignment_id, claimed_by='codex')
                if record is None:
                    raise work_lock.WorkLockError('; '.join(errors))
            work_lock.acquire(repo_root, logical_id, holder_agent="codex", route="codex_local_builder",
                              assignment_id=assignment_id, resume=bool(assignment_id),
                              run_id=run_id, base_sha=str(task.get("base_sha") or ""),
                              branch=str(task.get("new_branch") or ""))
        except (work_lock.WorkLockError, OSError) as exc:
            return {"status": "skipped", "reason": str(exc)}
        result = run_local_builder(repo_root, task_path=task_path, work_lock_run_id=run_id)
        work_lock.heartbeat(repo_root, logical_id, run_id=run_id, state=result.status)
        if assignment_id and result.status in {"failed_launch", "stalled", "timed_out"}:
            from orchestrator.event_router import route_completion
            from orchestrator.runtime_store import RunState
            route_completion(repo_root, RunState(
                run_id=result.run_id, assignment_id=assignment_id, task_id=task_id,
                assigned_agent="codex", adapter="codex-restricted", logical_task_id=logical_id,
                process_state=result.status, worktree=result.worktree_path,
                handoff_path=result.handoff_path, blocked_reason="; ".join(result.blocked_reasons),
            ), source="codex")
        elif assignment_id:
            from dispatch.assignment_channel import complete_assignment
            complete_assignment(repo_root, assignment_id, run_id=result.run_id,
                                handoff_path=result.handoff_path or None,
                                outbox_status='failed' if result.status in {'failed', 'failed_launch', 'stalled', 'timed_out', 'blocked'} else 'awaiting_review')
        return {
            "status": "processed",
            "run_id": result.run_id,
            "task_id": result.task_id,
            "result_status": result.status,
            "worktree_path": result.worktree_path,
            "handoff_path": result.handoff_path,
            "blocked_reasons": result.blocked_reasons,
        }
    finally:
        release_claim(repo_root, task_id)


def main() -> int:
    parser = argparse.ArgumentParser(description="Local builder worker (manual start).")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--once", action="store_true", help="Process one eligible task and exit")
    parser.add_argument("--task", help="Specific task YAML path")
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    signal.signal(signal.SIGINT, _handle_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_stop)

    task_path = Path(args.task) if args.task else None
    if task_path and not task_path.is_absolute():
        task_path = (root / task_path).resolve()

    if args.once:
        report = process_one(root, task_path=task_path)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(json.dumps(report, indent=2))
        return 0 if report.get("status") in {"processed", "idle"} else 1

    while not STOP_REQUESTED:
        report = process_one(root, task_path=task_path)
        if args.json:
            print(json.dumps(report, indent=2))
        if report.get("status") == "idle":
            time.sleep(max(1, args.poll_seconds))
        elif task_path is not None:
            break
        else:
            time.sleep(max(1, args.poll_seconds))

    return 0


if __name__ == "__main__":
    if __package__:
        from ._console import configure_console
    else:
        from _console import configure_console

    configure_console()
    raise SystemExit(main())
