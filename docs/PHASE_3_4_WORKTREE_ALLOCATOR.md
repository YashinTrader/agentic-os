# Phase 3.4 — Worktree Allocator MVP

**Status:** implemented  
**Autonomy level:** Level 1 (operator-commanded CLI only)

## Purpose

Isolate file-writing dispatch runs in Git worktrees. The allocator is **never auto-invoked**; operators run `scripts/allocate_worktree.py` explicitly.

## Modules and scripts

| Artifact | Role |
|----------|------|
| `dispatch/worktree_allocator.py` | Allocate, inspect, cleanup; gate helper |
| `dispatch/worktree_registry.py` | File-based allocation records |
| `scripts/allocate_worktree.py` | Operator CLI: create worktree |
| `scripts/inspect_worktree.py` | Operator CLI: inspect allocation |
| `scripts/cleanup_worktree.py` | Operator CLI: remove worktree |
| `schemas/worktree_allocation_record.schema.json` | Record validation |

## Lifecycle

1. Operator calls `allocate_worktree()` with `task_id`, `run_id`, `base_sha`.
2. Record saved as `requested` → `allocated` (or `failed`).
3. Execution gate requires matching allocation for `writes_files` adapters.
4. Operator inspects or cleans up via CLI.

**Status enum:** `requested` → `allocated` → (`active` | `failed`) → (`preserved` | `cleanup_pending`) → `cleaned`

## Safety invariants (implemented)

- **Operator-commanded only** — no executor or scheduler calls `allocate_worktree()`.
- **Path containment** — worktree path must stay inside `worktree_root` (`path_is_inside`).
- **Branch sanitization** — `agentic/<task>/<run>`; control chars and `..` rejected.
- **Git allowlist** — only `rev-parse`, `status`, `worktree`, `merge-base`; `shell=False`.
- **Duplicate blocking** — active `run_id`, branch, or path collisions rejected.
- **Dirty cleanup refused** — uncommitted changes → status `preserved`, cleanup fails.
- **No auto-merge** — allocator never merges or pushes.

## Configuration

- Default worktree root: `<repo-parent>/<repo-name>-worktrees`
- Override: `AGENTIC_OS_WORKTREE_ROOT` (absolute or sibling-relative)
- Default TTL: 24 hours (`expires_at` on record)

## Execution gate binding

`evaluate_allocation_for_execution()` requires:

- Status `allocated` or `active`
- Matching `task_id`, `run_id`, `base_sha`
- `cwd` and all `scope_paths` inside allocated worktree

File-writing execution **without** an allocation record is blocked.

## Known limitations

- No automatic allocation during `execute_dispatch.py`
- No dashboard allocate/cleanup buttons
- Cleanup does not force-remove dirty trees (by design)
- Real adapters with `writes_files: true` remain preview-only until promoted