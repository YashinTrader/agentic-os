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

from dispatch.atomic_io import atomic_create_json  # noqa: E402
from dispatch.codex_local_builder import run_local_builder  # noqa: E402
from dispatch.codex_local_builder_gate import task_execution_mode  # noqa: E402
from dispatch.execution_policy import MODE_AUTO_LOCAL_WORKTREE, load_execution_policy  # noqa: E402
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
        if task_execution_mode(task) != MODE_AUTO_LOCAL_WORKTREE:
            continue
        status = str(task.get("status", "")).lower()
        if status not in {"ready", "queued"}:
            continue
        task_id = str(task.get("id", path.stem))
        if (_claim_dir(repo_root) / f"{task_id}.json").exists():
            continue
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

    try:
        result = run_local_builder(repo_root, task_path=task_path)
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
    raise SystemExit(main())