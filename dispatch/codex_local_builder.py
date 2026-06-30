"""Codex local builder — standing-policy autonomous worktree development."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dispatch.agent_context_bundle import build_context_bundle
from dispatch.agent_environment import build_minimal_environment, merge_allowlists
from dispatch.codex_adapter import build_codex_command, load_codex_restricted_adapter
from dispatch.codex_local_builder_gate import (
    evaluate_changed_paths_scope,
    evaluate_local_builder_gates,
)
from dispatch.execution_policy import load_execution_policy
from dispatch.execution_route_policy import ROUTE_CODEX_LOCAL_BUILDER
from dispatch.runtime_capture import run_directory
from dispatch.worktree_allocator import (
    allocate_worktree,
    git_worktree_dirty,
    git_worktree_head,
    run_git,
)
from dispatch.worktree_registry import allocation_record_to_dict
from orchestrator.loaders import load_task_yaml

SubprocessRunner = Callable[..., subprocess.CompletedProcess[str]]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def generate_run_id(task_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:8]
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", task_id.strip()).strip("-")[:24]
    return f"build-{stamp}-{safe}-{suffix}"


RESULT_COMPLETED_VERIFIED = "completed_verified"
RESULT_COMPLETED_UNVERIFIED = "completed_unverified"
RESULT_BLOCKED = "blocked"
RESULT_FAILED = "failed"
RESULT_TIMED_OUT = "timed_out"
RESULT_SCOPE_VIOLATION = "scope_violation"


@dataclass
class LocalBuilderResult:
    run_id: str
    task_id: str
    status: str
    exit_code: int | None = None
    timed_out: bool = False
    worktree_path: str = ""
    allocation_id: str = ""
    handoff_path: str = ""
    blocked_reasons: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    verification_results: dict[str, Any] = field(default_factory=dict)
    run_dir: str = ""
    codex_subprocess_invoked: bool = False


def _git_porcelain_status(worktree: Path) -> str:
    code, out, _ = run_git(worktree, ["status", "--porcelain"])
    return out if code == 0 else ""


def _git_changed_files(worktree: Path) -> list[str]:
    code, out, _ = run_git(worktree, ["status", "--porcelain"])
    if code != 0:
        return []
    files: list[str] = []
    for line in out.splitlines():
        line = line.strip()
        if len(line) < 4:
            continue
        path_part = line[3:].strip()
        if " -> " in path_part:
            path_part = path_part.split(" -> ", 1)[1].strip()
        files.append(path_part.replace("\\", "/"))
    return sorted(set(files))


def _git_diff_patch(worktree: Path) -> str:
    code, out, _ = run_git(worktree, ["diff"])
    if code != 0:
        return ""
    code2, staged, _ = run_git(worktree, ["diff", "--cached"])
    if code2 != 0:
        return out
    return (staged + out).strip() + ("\n" if staged or out else "")


def _run_shell_command(
    command: str,
    *,
    cwd: Path,
    timeout: int,
    runner: SubprocessRunner | None = None,
) -> dict[str, Any]:
    run = runner or subprocess.run
    argv = shlex.split(command, posix=(os.name != "nt"))
    try:
        completed = run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        return {
            "command": command,
            "exit_code": completed.returncode,
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "exit_code": None,
            "stdout": (exc.stdout or b"").decode("utf-8", errors="replace"),
            "stderr": (exc.stderr or b"").decode("utf-8", errors="replace"),
            "timed_out": True,
        }
    except FileNotFoundError as exc:
        return {
            "command": command,
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
            "timed_out": False,
            "error": str(exc),
        }


def _build_prompt(instructions_path: Path, handoff_rel: str) -> str:
    return (
        f"Follow instructions in {instructions_path}. "
        f"Write the required handoff to {handoff_rel} in the worktree. "
        "Inspect existing code before editing. Modify only allowed paths. "
        "Do not push, merge, deploy, or access production. "
        "Run required verification commands. Stop after completion or a clear blocker."
    )


def run_local_builder(
    repo_root: Path,
    *,
    task_path: Path,
    base_sha: str | None = None,
    codex_executable: str | None = None,
    cli_version: str | None = None,
    subprocess_runner: SubprocessRunner | None = None,
    skip_codex: bool = False,
    fake_codex_exit: int = 0,
) -> LocalBuilderResult:
    """Execute one local-builder run. subprocess_runner injectable for tests."""
    repo_root = repo_root.resolve()
    task = load_task_yaml(task_path)
    task_id = str(task.get("id", ""))
    if not task_id:
        raise ValueError("task id missing")

    adapter = load_codex_restricted_adapter(repo_root)
    policy = load_execution_policy(repo_root)
    execution = task.get("execution") or {}
    verification = task.get("verification") or {}
    timeout_seconds = int(execution.get("timeout_seconds") or adapter.get("timeout_seconds") or 1800)
    allowed_paths = list(execution.get("allowed_paths") or [])
    verification_commands = list(verification.get("commands") or ["python scripts/validate.py"])
    run_full_tests = bool(verification.get("run_full_tests"))
    if run_full_tests:
        verification_commands.append("python scripts/run_tests.py")

    run_id = generate_run_id(task_id)
    run_dir = run_directory(repo_root, run_id)
    started_at = utc_now()

    base = base_sha or str(task.get("base_sha") or "").strip()
    if not base:
        code, out, _ = run_git(repo_root, ["rev-parse", "HEAD"])
        base = out.strip() if code == 0 else ""

    alloc = allocate_worktree(
        repo_root,
        task_id=task_id,
        run_id=run_id,
        base_sha=base,
        owner="codex-local-builder",
        cleanup_policy="manual",
    )
    if not alloc.success or alloc.record is None:
        return LocalBuilderResult(
            run_id=run_id,
            task_id=task_id,
            status=RESULT_BLOCKED,
            blocked_reasons=alloc.errors or ["worktree allocation failed"],
            run_dir=str(run_dir),
        )

    allocation_record = allocation_record_to_dict(alloc.record)
    worktree_path = str(allocation_record.get("worktree_path", alloc.worktree_path))
    worktree = Path(worktree_path).resolve()

    gate = evaluate_local_builder_gates(
        repo_root,
        task=task,
        adapter=adapter,
        allocation_record=allocation_record,
        policy=policy,
    )
    if not gate.allowed:
        _write_blocked_artifacts(
            repo_root,
            run_dir,
            task=task,
            policy=policy,
            allocation_record=allocation_record,
            gate=gate,
            started_at=started_at,
        )
        return LocalBuilderResult(
            run_id=run_id,
            task_id=task_id,
            status=RESULT_BLOCKED,
            blocked_reasons=gate.blocked_reasons,
            worktree_path=worktree_path,
            allocation_id=str(allocation_record.get("allocation_id", "")),
            run_dir=str(run_dir),
        )

    git_status_before = _git_porcelain_status(worktree)
    (run_dir / "git_status_before.txt").write_text(git_status_before, encoding="utf-8")
    (run_dir / "task.yaml").write_text(task_path.read_text(encoding="utf-8"), encoding="utf-8")
    (run_dir / "execution_policy.json").write_text(json.dumps(policy, indent=2), encoding="utf-8")
    (run_dir / "worktree_allocation.json").write_text(
        json.dumps(allocation_record, indent=2), encoding="utf-8"
    )

    preview = {
        "adapter_id": "codex-restricted",
        "task_id": task_id,
        "run_id": run_id,
        "execution_route": ROUTE_CODEX_LOCAL_BUILDER,
        "working_directory": worktree_path,
        "timeout_seconds": timeout_seconds,
        "allowed_paths": allowed_paths,
    }
    handoff_rel = f"handoffs/{task_id}__codex__to__claude.md"
    bundle_manifest = build_context_bundle(
        repo_root,
        run_id=run_id,
        task=task,
        plan=None,
        preview=preview,
        adapter_policy=adapter,
        worktree_path=worktree_path,
        base_sha=base,
        allowed_paths=allowed_paths,
        forbidden_operations=list(execution.get("forbidden_operations") or []),
        verification_commands=verification_commands,
    )

    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    agent_output_path = worktree / "runtime" / "codex_agent_output.json"
    agent_output_path.parent.mkdir(parents=True, exist_ok=True)

    plan = build_codex_command(
        adapter,
        repo_root=repo_root,
        worktree_path=worktree_path,
        run_id=run_id,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        agent_output_path=str(agent_output_path),
        timeout_seconds=timeout_seconds,
        cli_version=cli_version,
        allocation_record=allocation_record,
        task_id=task_id,
        base_sha=base,
        scope_paths=["."],
        prompt=_build_prompt(
            repo_root / "runtime" / "dispatch" / "runs" / run_id / "codex_context" / "instructions.md",
            handoff_rel,
        ),
    )
    if plan.blocked_reasons:
        return LocalBuilderResult(
            run_id=run_id,
            task_id=task_id,
            status=RESULT_BLOCKED,
            blocked_reasons=plan.blocked_reasons,
            worktree_path=worktree_path,
            allocation_id=str(allocation_record.get("allocation_id", "")),
            run_dir=str(run_dir),
        )

    (run_dir / "command.json").write_text(
        json.dumps({"argv": plan.argv, "cwd": plan.cwd}, indent=2), encoding="utf-8"
    )
    allow = merge_allowlists(adapter.get("environment_allowlist"))
    deny = frozenset(adapter.get("environment_denylist") or [])
    env, env_names = build_minimal_environment(allowlist=allow, denylist=deny)
    (run_dir / "environment_names.json").write_text(json.dumps(env_names, indent=2), encoding="utf-8")

    exit_code: int | None = None
    timed_out = False
    codex_invoked = False

    if skip_codex:
        exit_code = fake_codex_exit
        stdout_path.write_text("codex skipped (test mode)\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
    else:
        codex_invoked = True
        argv = list(plan.argv)
        if codex_executable:
            argv[0] = codex_executable
        runner = subprocess_runner or subprocess.run
        try:
            completed = runner(
                argv,
                cwd=plan.cwd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
                shell=False,
            )
            exit_code = completed.returncode
            stdout_path.write_text(completed.stdout or "", encoding="utf-8")
            stderr_path.write_text(completed.stderr or "", encoding="utf-8")
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout_path.write_text((exc.stdout or b"").decode("utf-8", errors="replace"), encoding="utf-8")
            stderr_path.write_text((exc.stderr or b"").decode("utf-8", errors="replace"), encoding="utf-8")
        except OSError as exc:
            stderr_path.write_text(str(exc) + "\n", encoding="utf-8")

    if agent_output_path.is_file():
        (run_dir / "agent_output.json").write_text(
            agent_output_path.read_text(encoding="utf-8"), encoding="utf-8"
        )

    git_status_after = _git_porcelain_status(worktree)
    (run_dir / "git_status_after.txt").write_text(git_status_after, encoding="utf-8")
    changed_files = _git_changed_files(worktree)
    diff_patch = _git_diff_patch(worktree)
    (run_dir / "git_diff.patch").write_text(diff_patch, encoding="utf-8")

    scope_ok, scope_errors = evaluate_changed_paths_scope(worktree, changed_files, allowed_paths)
    verification_results: dict[str, Any] = {"commands": []}
    for cmd in verification_commands:
        verification_results["commands"].append(
            _run_shell_command(cmd, cwd=worktree, timeout=min(timeout_seconds, 600), runner=subprocess_runner)
        )
    validator_ok = all(
        c.get("exit_code") == 0 and not c.get("timed_out")
        for c in verification_results["commands"]
    )
    (run_dir / "verification_results.json").write_text(
        json.dumps(verification_results, indent=2), encoding="utf-8"
    )

    handoff_path = worktree / handoff_rel
    handoff_exists = handoff_path.is_file()
    if handoff_exists:
        (run_dir / "handoff.md").write_text(handoff_path.read_text(encoding="utf-8"), encoding="utf-8")

    if not scope_ok:
        status = RESULT_SCOPE_VIOLATION
        blocked = scope_errors
    elif timed_out:
        status = RESULT_TIMED_OUT
        blocked = ["codex subprocess timed out"]
    elif exit_code not in (0, None) and exit_code != 0:
        status = RESULT_FAILED
        blocked = [f"codex exit code {exit_code}"]
    elif not handoff_exists:
        status = RESULT_FAILED
        blocked = ["required handoff missing"]
    elif not validator_ok:
        status = RESULT_COMPLETED_UNVERIFIED
        blocked = ["verification commands did not all pass"]
    else:
        status = RESULT_COMPLETED_VERIFIED
        blocked = []

    finished_at = utc_now()
    result_payload = {
        "run_id": run_id,
        "task_id": task_id,
        "adapter_id": "codex-restricted",
        "route": ROUTE_CODEX_LOCAL_BUILDER,
        "status": status,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "started_at": started_at,
        "finished_at": finished_at,
        "worktree_path": worktree_path,
        "allocation_id": str(allocation_record.get("allocation_id", "")),
        "changed_files": changed_files,
        "handoff_path": str(handoff_path) if handoff_exists else "",
        "handoff_rel": handoff_rel,
        "blocked_reasons": blocked,
        "codex_subprocess_invoked": codex_invoked,
        "bundle_hash": bundle_manifest.get("bundle_hash", ""),
        "git_head_after": git_worktree_head(repo_root, worktree),
        "worktree_dirty": git_worktree_dirty(repo_root, worktree),
    }
    (run_dir / "result.json").write_text(json.dumps(result_payload, indent=2), encoding="utf-8")

    return LocalBuilderResult(
        run_id=run_id,
        task_id=task_id,
        status=status,
        exit_code=exit_code,
        timed_out=timed_out,
        worktree_path=worktree_path,
        allocation_id=str(allocation_record.get("allocation_id", "")),
        handoff_path=str(handoff_path) if handoff_exists else "",
        blocked_reasons=blocked,
        changed_files=changed_files,
        verification_results=verification_results,
        run_dir=str(run_dir),
        codex_subprocess_invoked=codex_invoked,
    )


def _write_blocked_artifacts(
    repo_root: Path,
    run_dir: Path,
    *,
    task: dict[str, Any],
    policy: dict[str, Any],
    allocation_record: dict[str, Any],
    gate: Any,
    started_at: str,
) -> None:
    payload = {
        "status": RESULT_BLOCKED,
        "blocked_reasons": gate.blocked_reasons,
        "gate_results": gate.gate_results,
        "started_at": started_at,
        "finished_at": utc_now(),
    }
    (run_dir / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (run_dir / "execution_policy.json").write_text(json.dumps(policy, indent=2), encoding="utf-8")
    (run_dir / "worktree_allocation.json").write_text(
        json.dumps(allocation_record, indent=2), encoding="utf-8"
    )
    (run_dir / "task.yaml").write_text(json.dumps(task, indent=2), encoding="utf-8")