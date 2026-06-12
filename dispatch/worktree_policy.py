"""Phase 3.2 worktree and sandbox path policy — validation only."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WorktreePolicyResult:
    allowed: bool
    blocked_reasons: list[str] = field(default_factory=list)
    worktree_required: bool = False
    worktree_configured: bool = False


def _resolve_inside(base: Path, candidate: str) -> tuple[Path | None, str | None]:
    """Resolve candidate path and ensure it stays inside base. Blocks traversal."""
    if not candidate or not str(candidate).strip():
        return None, "empty path"
    try:
        base_resolved = base.resolve()
        raw = Path(candidate)
        if raw.is_absolute():
            resolved = raw.resolve()
        else:
            resolved = (base_resolved / raw).resolve()
        if not str(resolved).startswith(str(base_resolved)):
            return None, f"path escapes sandbox: {candidate!r}"
        return resolved, None
    except (OSError, ValueError) as exc:
        return None, f"path resolution failed for {candidate!r}: {exc}"


def allowed_roots(repo_root: Path, worktree_root: str | None = None) -> list[Path]:
    roots = [repo_root.resolve()]
    if worktree_root:
        wt = Path(worktree_root)
        if wt.is_absolute():
            roots.append(wt.resolve())
        else:
            roots.append((repo_root / wt).resolve())
    return roots


def path_inside_any_root(path: Path, roots: list[Path]) -> bool:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def evaluate_worktree_policy(
    repo_root: Path,
    *,
    cwd: str,
    scope_paths: list[str] | tuple[str, ...],
    writes_files: bool,
    worktree_required: bool,
    worktree_root: str | None = None,
) -> WorktreePolicyResult:
    """Enforce cwd/scope sandbox and worktree requirements for execution."""
    repo_root = repo_root.resolve()
    blocked: list[str] = []
    roots = allowed_roots(repo_root, worktree_root)
    worktree_configured = worktree_root is not None and bool(str(worktree_root).strip())

    if writes_files and worktree_required and not worktree_configured:
        blocked.append(
            "writes_files=true requires configured worktree; automatic worktree creation "
            "is not enabled in Phase 3.2 MVP"
        )

    cwd_path, cwd_err = _resolve_inside(repo_root, cwd)
    if cwd_err:
        blocked.append(f"cwd invalid: {cwd_err}")
    elif cwd_path is not None and not path_inside_any_root(cwd_path, roots):
        blocked.append(f"cwd {cwd!r} is outside repo or approved worktree roots")

    for scope in scope_paths or []:
        scope_str = str(scope)
        if scope_str.endswith("/") or scope_str.endswith("\\"):
            base_for_scope = repo_root
        else:
            base_for_scope = repo_root
        scope_path, scope_err = _resolve_inside(base_for_scope, scope_str)
        if scope_err:
            blocked.append(f"scope_path invalid: {scope_err}")
        elif scope_path is not None and not path_inside_any_root(scope_path, roots):
            blocked.append(f"scope_path {scope_str!r} is outside repo or approved worktree roots")

    return WorktreePolicyResult(
        allowed=len(blocked) == 0,
        blocked_reasons=blocked,
        worktree_required=worktree_required,
        worktree_configured=worktree_configured,
    )