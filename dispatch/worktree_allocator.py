"""Phase 3.4 operator-commanded Git worktree allocator — explicit CLI only."""

from __future__ import annotations

import os
import hashlib
import re
import subprocess
import shutil
import tempfile
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
MAX_WORKTREE_PATH_LENGTH = 199
MAX_ALLOCATION_ATTEMPTS = 8
DEFAULT_ALLOCATION_TTL_HOURS = 24

ALLOWED_GIT_SUBCOMMANDS = frozenset(
    {"rev-parse", "status", "worktree", "merge-base", "diff", "clone", "checkout", "fetch", "bundle", "init"}
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


def unique_run_slug(run_id: str) -> str:
    """Stable 96-bit digest of the FULL validated run id, including its suffix."""
    sanitize_run_id(run_id)  # Validate without hashing the truncated sanitizer output.
    return hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:24]


def build_branch_name(task_id: str, run_id: str) -> str:
    task_part = sanitize_task_id(task_id)
    short_run = unique_run_slug(run_id)
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
    short_run = unique_run_slug(run_id)
    # Budget: absolute root + 2 separators + task (<=60) + run slug (24).
    # Shorten only the task component; never truncate the run identity.
    budget = MAX_WORKTREE_PATH_LENGTH - len(str(worktree_root.resolve())) - 2 - len(short_run)
    if budget < 1:
        raise ValueError("configured worktree root exceeds 199-character path budget")
    task_part = task_part[:budget].rstrip("/.") or "t"
    candidate = (worktree_root / task_part / short_run).resolve()
    if len(str(candidate)) > MAX_WORKTREE_PATH_LENGTH:
        raise ValueError("worktree path exceeds 199-character path budget")
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


def run_git(repo_root: Path, argv: list[str], *, timeout: int = GIT_TIMEOUT_SECONDS,
            local_only: bool = False) -> tuple[int, str, str]:
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

    from orchestrator.process_ownership import owned_run
    environment = None
    if local_only:
        environment = {key: value for key, value in os.environ.items() if not key.upper().startswith('GIT_')}
        environment.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                           GIT_ALLOW_PROTOCOL='file', GIT_TERMINAL_PROMPT='0')
    proc = owned_run([GIT_EXECUTABLE, *argv], cwd=repo_root, timeout=timeout, shell=False,
                     **({'env': environment} if local_only else {}))
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
    _attempt: int = 0,
    standalone_clone: bool = False,
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
    if errors:
        return AllocationResult(False, None, str(worktree_path), branch_name, errors)

    for attempt in range(_attempt, MAX_ALLOCATION_ATTEMPTS):
        # Retry identities include fresh entropy, but the registry retains the real run_id.
        identity = run_id if attempt == 0 else f"{run_id}-allocation-{uuid4().hex}"
        branch_name = build_branch_name(task_id, identity)
        worktree_path = build_worktree_path(worktree_root, task_id, identity)
        conflicts = assert_no_active_duplicate(
            repo_root, run_id=run_id, branch_name=branch_name,
            worktree_path=str(worktree_path),
        )
        same_run = [reason for reason in conflicts if reason.startswith("active allocation already exists for run_id ")]
        if same_run:
            return AllocationResult(False, None, str(worktree_path), branch_name, same_run)
        branch_exists, _, _ = run_git(
            repo_root, ["rev-parse", "--verify", f"refs/heads/{branch_name}"]
        )
        if not conflicts and not worktree_path.exists() and branch_exists != 0:
            break
    else:
        return AllocationResult(False, None, str(worktree_path), branch_name,
                                ["worktree allocation collision retry limit reached"])

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
    if standalone_clone:
        # A bundle-backed clone has independent objects and refs. Even --local
        # clone uses shell-based upload-pack on the installed Git for Windows;
        # init + bundle fetch avoids that transport entirely.
        worktree_path.mkdir()
        provision = worktree_path / '.agentic/provision.bundle'
        provision.parent.mkdir()
        code, out, err = run_git(worktree_path, ['init', '--quiet'], local_only=True)
        if code == 0:
            code, out, err = run_git(repo_root, ['bundle', 'create', str(provision), '--all'], local_only=True)
        if code == 0:
            code, out, err = run_git(worktree_path, ['fetch', '--no-tags', '--no-write-fetch-head',
                './.agentic/provision.bundle', '+refs/heads/*:refs/remotes/source/*',
                '+refs/tags/*:refs/tags/*'], local_only=True)
        if code == 0:
            provision.unlink()
        if code == 0:
            code, out, err = run_git(worktree_path, ["checkout", "-b", branch_name, base_sha], local_only=True)
    else:
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
        # A competing allocator may have claimed the name after the preflight.
        branch_exists, _, _ = run_git(repo_root, ["rev-parse", "--verify", f"refs/heads/{branch_name}"])
        if (worktree_path.exists() or branch_exists == 0) and attempt + 1 < MAX_ALLOCATION_ATTEMPTS:
            return allocate_worktree(
                repo_root, task_id=task_id, run_id=run_id, base_sha=base_sha,
                base_branch=base_branch, owner=owner, cleanup_policy=cleanup_policy,
                _attempt=attempt + 1,
                standalone_clone=standalone_clone,
            )
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


def import_builder_results(repo_root: Path, workspace: Path, branch: str) -> None:
    """Medium supervisor imports commits; builder never writes supervisor Git."""
    from orchestrator.builder_isolation import standalone_workspace
    standalone_workspace(workspace)
    if os.name == 'nt':
        from orchestrator.builder_isolation import assert_medium_tree
        assert_medium_tree(workspace)
    if not branch or branch.startswith('-') or not re.fullmatch(r'[A-Za-z0-9._/-]+', branch):
        raise ValueError('invalid builder result branch')
    # The builder may have changed local Git config. Do not execute its filters,
    # fsmonitor or upload-pack hooks with the supervisor's Medium token.
    hooks = workspace / ('.agentic/supervisor-disabled-hooks-' + uuid4().hex)
    hooks.mkdir(parents=True, exist_ok=False)
    (workspace / '.git/config').write_text(
        '[core]\n\trepositoryformatversion = 0\n\tbare = false\n'
        '\tfsmonitor = false\n\thooksPath = "' + hooks.resolve().as_posix() + '"\n', encoding='utf-8')
    # A local bundle avoids Git for Windows' shell-based upload-pack transport.
    # The supervisor has stopped the builder tree and sanitized its Git config.
    bundle = workspace / ('.agentic/supervisor-results-' + uuid4().hex + '.bundle')
    code, out, err = run_git(workspace, ['bundle', 'create', str(bundle.resolve()), f'refs/heads/{branch}'], local_only=True)
    if code:
        raise OSError('builder results bundle failed: ' + (err or out).strip())
    # POSIX Git builds can interpret C:\\... source arguments as SSH remotes.
    # Both clone and fetch use unambiguous local relative sources. A Medium
    # temporary copy also supports workspaces provisioned on another drive.
    root = repo_root.resolve()
    with tempfile.TemporaryDirectory(prefix='agentic-import-', dir=root/'.git') as directory:
        exported = Path(directory)/'results.bundle'
        shutil.copyfile(bundle, exported)
        source = './' + exported.relative_to(root).as_posix()
        code, out, err = run_git(root, ['fetch', '--no-tags', '--no-write-fetch-head', source,
                                       f'refs/heads/{branch}:refs/heads/{branch}'], local_only=True)
    if code:
        raise OSError('builder results fetch failed: ' + (err or out).strip())


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
