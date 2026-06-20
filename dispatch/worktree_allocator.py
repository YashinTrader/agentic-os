"""Phase 3.4 operator-commanded Git worktree allocator — explicit CLI only."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from dispatch.path_containment import path_is_inside
from dispatch.worktree_registry import (
    AllocationRecord,
    assert_no_active_duplicate,
    new_allocation_id,
    save_allocation_record,
    transition_status,
    utc_now,
)

GIT_EXECUTABLE = "git"
GIT_TIMEOUT_SECONDS = 120
MAX_BRANCH_LENGTH = 120
DEFAULT_ALLOCATION_TTL_HOURS = 24

ALLOWED_GIT_SUBCOMMANDS = frozenset(
    {"rev-parse", "status", "worktree", "merge-base"}
)

_UNSAFE_BRANCH_CHARS = re.compile(r"[^a-zA-Z0-9._/-]+")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass
class AllocationResult:
    success: bool
    record: AllocationRecord | None
    worktree_path: str
    branch_name: str
    errors: list[str]


@dataclass
class CleanupResult:
    success: bool
    record: AllocationRecord | None
    errors: list[str]


@dataclass
class InspectResult:
    record: AllocationRecord | None
    dirty: bool
    git_head: str
    errors: list[str]


def resolve_worktree_root(repo_root: Path) -> Path:
    """Resolve configured worktree root (sibling dir or env override)."""
    override = os.environ.get("AGENTIC_OS_WORKTREE_ROOT", "").strip()
    if override:
        root = Path(override).expanduser()
        if not root.is_absolute():
            root = (repo_root.parent / root).resolve()
        else:
            root = root.resolve()
    else:
        root = (repo_root.parent / f"{repo_root.name}-worktrees").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def sanitize_task_id(task_id: str) -> str:
    raw = task_id.strip()
    if not raw:
        raise ValueError("task_id must not be empty")
    if _CONTROL_CHARS.search(raw) or ".." in raw or "@{" in raw:
        raise ValueError(f"unsafe task_id: {task_id!r}")
    cleaned = _UNSAFE_BRANCH_CHARS.sub("-", raw)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-/").lower()
    if not cleaned:
        raise ValueError(f"task_id sanitization produced empty result: {task_id!r}")
    return cleaned[:60]


def sanitize_run_id(run_id: str) -> str:
    raw = run_id.strip()
    if not raw:
        raise ValueError("run_id must not be empty")
    if _CONTROL_CHARS.search(raw) or ".." in raw or "@{" in raw:
        raise ValueError(f"unsafe run_id: {run_id!r}")
    cleaned = _UNSAFE_BRANCH_CHARS.sub("-", raw)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-/")
    if not cleaned:
        raise ValueError(f"run_id sanitization produced empty result: {run_id!r}")
    return cleaned[:40]


def build_branch_name(task_id: str, run_id: str) -> str:
    task_part = sanitize_task_id(task_id)
    run_part = sanitize_run_id(run_id)
    short_run = run_part[:12] if len(run_part) > 12 else run_part
    branch = f"agentic/{task_part}/{short_run}"
    if len(branch) > MAX_BRANCH_LENGTH:
        raise ValueError(f"branch name exceeds {MAX_BRANCH_LENGTH} characters")
    if not re.fullmatch(r"[a-zA-Z0-9._/-]+", branch):
        raise ValueError(f"branch name contains unsafe characters: {branch!r}")
    if branch.startswith("/") or branch.endswith("/") or "//" in branch:
        raise ValueError(f"invalid branch structure: {branch!r}")
    return branch


def build_worktree_path(worktree_root: Path, task_id: str, run_id: str) -> Path:
    task_part = sanitize_task_id(task_id)
    run_part = sanitize_run_id(run_id)
    short_run = run_part[:12] if len(run_part) > 12 else run_part
    candidate = (worktree_root / task_part / short_run).resolve()
    if not path_is_inside(candidate, worktree_root.resolve(), allow_equal=True):
        raise ValueError("worktree path escapes configured worktree root")
    return candidate


def _validate_base_inside_repo(repo_root: Path, base_sha: str) -> list[str]:
    errors: list[str] = []
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", base_sha):
        errors.append(f"invalid base_sha format: {base_sha!r}")
        return errors
    code, out, err = run_git(repo_root, ["rev-parse", "--verify", f"{base_sha}^{{commit}}"])
    if code != 0:
        errors.append(f"base_sha not found in repository: {base_sha!r} ({err.strip()})")
    return errors


def run_git(repo_root: Path, argv: list[str], *, timeout: int = GIT_TIMEOUT_SECONDS) -> tuple[int, str, str]:
    """Run allowlisted git command with argv list only (no shell)."""
    if not argv:
        raise ValueError("git argv must not be empty")
    subcommand = argv[0]
    if subcommand not in ALLOWED_GIT_SUBCOMMANDS:
        raise ValueError(f"git subcommand not allowlisted: {subcommand!r}")
    if subcommand == "worktree" and len(argv) < 2:
        raise ValueError("git worktree requires a sub-subcommand")
    if subcommand == "worktree" and argv[1] not in {"add", "remove", "list", "prune"}:
        raise ValueError(f"git worktree subcommand not allowlisted: {argv[1]!r}")

    proc = subprocess.run(
        [GIT_EXECUTABLE, *argv],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def git_worktree_dirty(repo_root: Path, worktree_path: Path) -> bool:
    code, out, _ = run_git(worktree_path, ["status", "--porcelain"])
    if code != 0:
        return True
    return bool(out.strip())


def git_worktree_head(repo_root: Path, worktree_path: Path) -> str:
    code, out, _ = run_git(worktree_path, ["rev-parse", "HEAD"])
    if code != 0:
        return ""
    return out.strip()


def git_worktree_list_contains(repo_root: Path, worktree_path: Path) -> bool:
    code, out, _ = run_git(repo_root, ["worktree", "list", "--porcelain"])
    if code != 0:
        return False
    target = str(worktree_path.resolve())
    for line in out.splitlines():
        if line.startswith("worktree "):
            listed = line[len("worktree ") :].strip()
            if str(Path(listed).resolve()) == target:
                return True
    return False


def allocate_worktree(
    repo_root: Path,
    *,
    task_id: str,
    run_id: str,
    base_sha: str,
    base_branch: str = "",
    owner: str = "operator",
    cleanup_policy: str = "manual",
) -> AllocationResult:
    """Operator-commanded worktree allocation. Never auto-invoked."""
    repo_root = repo_root.resolve()
    errors: list[str] = []

    try:
        worktree_root = resolve_worktree_root(repo_root)
        branch_name = build_branch_name(task_id, run_id)
        worktree_path = build_worktree_path(worktree_root, task_id, run_id)
    except ValueError as exc:
        return AllocationResult(False, None, "", "", [str(exc)])

    errors.extend(_validate_base_inside_repo(repo_root, base_sha))
    if worktree_path.exists():
        errors.append(f"worktree path already exists: {worktree_path}")
    errors.extend(
        assert_no_active_duplicate(
            repo_root,
            run_id=run_id,
            branch_name=branch_name,
            worktree_path=str(worktree_path),
        )
    )
    if errors:
        return AllocationResult(False, None, str(worktree_path), branch_name, errors)

    allocation_id = new_allocation_id()
    created_at = utc_now()
    expires = (
        datetime.now(timezone.utc) + timedelta(hours=DEFAULT_ALLOCATION_TTL_HOURS)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    requested = AllocationRecord(
        allocation_id=allocation_id,
        run_id=run_id,
        task_id=task_id,
        repo_root=str(repo_root),
        worktree_root=str(worktree_root),
        worktree_path=str(worktree_path),
        branch_name=branch_name,
        base_sha=base_sha,
        base_branch=base_branch,
        created_at=created_at,
        expires_at=expires,
        status="requested",
        cleanup_policy=cleanup_policy,
        writes_files=True,
        owner=owner,
        last_verified_at=created_at,
        dirty=False,
        git_head="",
        error="",
        audit=[],
    )
    save_allocation_record(repo_root, requested)

    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    code, out, err = run_git(
        repo_root,
        ["worktree", "add", "-b", branch_name, str(worktree_path), base_sha],
    )
    if code != 0:
        failed = AllocationRecord(
            allocation_id=allocation_id,
            run_id=run_id,
            task_id=task_id,
            repo_root=str(repo_root),
            worktree_root=str(worktree_root),
            worktree_path=str(worktree_path),
            branch_name=branch_name,
            base_sha=base_sha,
            base_branch=base_branch,
            created_at=created_at,
            expires_at=expires,
            status="failed",
            cleanup_policy=cleanup_policy,
            writes_files=True,
            owner=owner,
            last_verified_at=utc_now(),
            dirty=False,
            git_head="",
            error=err.strip() or out.strip() or "git worktree add failed",
            audit=[{"at": utc_now(), "event": "allocate_failed"}],
        )
        save_allocation_record(repo_root, failed)
        return AllocationResult(False, failed, str(worktree_path), branch_name, [failed.error])

    head = git_worktree_head(repo_root, worktree_path)
    allocated = AllocationRecord(
        allocation_id=allocation_id,
        run_id=run_id,
        task_id=task_id,
        repo_root=str(repo_root),
        worktree_root=str(worktree_root),
        worktree_path=str(worktree_path),
        branch_name=branch_name,
        base_sha=base_sha,
        base_branch=base_branch,
        created_at=created_at,
        expires_at=expires,
        status="allocated",
        cleanup_policy=cleanup_policy,
        writes_files=True,
        owner=owner,
        last_verified_at=utc_now(),
        dirty=False,
        git_head=head,
        error="",
        audit=[{"at": utc_now(), "event": "allocated"}],
    )
    save_allocation_record(repo_root, allocated)
    return AllocationResult(True, allocated, str(worktree_path), branch_name, [])


def inspect_worktree(repo_root: Path, allocation_id: str) -> InspectResult:
    from dispatch.worktree_registry import load_allocation_record

    errors: list[str] = []
    try:
        record = load_allocation_record(repo_root, allocation_id)
    except (OSError, ValueError) as exc:
        return InspectResult(None, True, "", [str(exc)])

    worktree_path = Path(record.worktree_path)
    worktree_root = Path(record.worktree_root).resolve()
    if not path_is_inside(worktree_path.resolve(), worktree_root, allow_equal=True):
        errors.append("worktree path outside configured worktree root")

    dirty = git_worktree_dirty(repo_root, worktree_path) if worktree_path.exists() else True
    head = git_worktree_head(repo_root, worktree_path) if worktree_path.exists() else ""
    return InspectResult(record, dirty, head, errors)


def cleanup_worktree(repo_root: Path, allocation_id: str) -> CleanupResult:
    from dispatch.worktree_registry import load_allocation_record

    errors: list[str] = []
    try:
        record = load_allocation_record(repo_root, allocation_id)
    except (OSError, ValueError) as exc:
        return CleanupResult(False, None, [str(exc)])

    worktree_path = Path(record.worktree_path).resolve()
    worktree_root = Path(record.worktree_root).resolve()
    if not path_is_inside(worktree_path, worktree_root, allow_equal=True):
        return CleanupResult(False, record, ["worktree path outside configured worktree root"])

    if not worktree_path.exists():
        updated = transition_status(repo_root, allocation_id, "cleaned", dirty=False)
        return CleanupResult(True, updated, [])

    if not git_worktree_list_contains(repo_root, worktree_path):
        errors.append("git does not recognize path as a registered worktree")
        return CleanupResult(False, record, errors)

    if git_worktree_dirty(repo_root, worktree_path):
        transition_status(repo_root, allocation_id, "preserved", dirty=True)
        return CleanupResult(False, record, ["refusing cleanup: worktree is dirty"])

    code, out, err = run_git(repo_root, ["worktree", "remove", str(worktree_path)])
    if code != 0:
        msg = err.strip() or out.strip() or "git worktree remove failed"
        transition_status(repo_root, allocation_id, "cleanup_pending", error=msg)
        return CleanupResult(False, record, [msg])

    updated = transition_status(repo_root, allocation_id, "cleaned", dirty=False, git_head="")
    return CleanupResult(True, updated, errors)


def evaluate_allocation_for_execution(
    record: AllocationRecord | dict[str, Any] | None,
    *,
    task_id: str,
    run_id: str,
    base_sha: str,
    cwd: str,
    scope_paths: list[str] | tuple[str, ...],
) -> list[str]:
    """Validate allocation record satisfies execution requirements for file-writing runs."""
    if record is None:
        return ["worktree allocation record required for file-writing execution"]

    data = record if isinstance(record, dict) else allocation_record_from_dict_for_gate(record)

    blocked: list[str] = []
    status = str(data.get("status", ""))
    if status not in {"allocated", "active"}:
        blocked.append(f"allocation status {status!r} does not allow execution")

    if str(data.get("task_id", "")) != task_id:
        blocked.append("allocation task_id does not match execution request")
    if str(data.get("run_id", "")) != run_id:
        blocked.append("allocation run_id does not match execution request")

    record_base = str(data.get("base_sha", ""))
    if record_base.lower() != base_sha.lower():
        blocked.append("allocation base_sha does not match expected base")

    worktree_path = Path(str(data.get("worktree_path", ""))).resolve()
    worktree_root = Path(str(data.get("worktree_root", ""))).resolve()
    if not path_is_inside(worktree_path, worktree_root, allow_equal=True):
        blocked.append("allocation worktree_path escapes worktree_root")

    try:
        cwd_path = Path(cwd).resolve()
    except OSError:
        blocked.append(f"invalid cwd: {cwd!r}")
        return blocked

    if not path_is_inside(cwd_path, worktree_path, allow_equal=True):
        blocked.append("execution cwd must be inside allocated worktree")

    for scope in scope_paths or []:
        scope_path = Path(str(scope))
        if scope_path.is_absolute():
            resolved = scope_path.resolve()
        else:
            resolved = (worktree_path / scope_path).resolve()
        if not path_is_inside(resolved, worktree_path, allow_equal=True):
            blocked.append(f"scope path {scope!r} escapes allocated worktree")

    return blocked


def allocation_record_from_dict_for_gate(record: AllocationRecord) -> dict[str, Any]:
    from dispatch.worktree_registry import allocation_record_to_dict

    return allocation_record_to_dict(record)