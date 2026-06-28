# Phase 3.3 — Git Worktree Allocator Design

**Status:** design only — no implementation in Phase 3.3  
**Current autonomy level:** Level 1 (explicit operator execution)

## Purpose

Define the contract for isolated Git worktree allocation before any file-writing agent adapter runs. Phase 3.2 executes only the `local-python-exec-test` fixture in repo root. Real adapters with `writes_files: true` require worktree isolation in a future phase.

## Lifecycle

1. Receive approved execution request (preview + approval + freshness verified).
2. Generate `run_id` (reuse dispatch preview run_id).
3. Derive sanitized branch name: `agent/<agent_id>/<task_id>/<run_id_suffix>`.
4. Verify clean source repository state (no uncommitted changes in scope unless policy allows stash).
5. Create isolated worktree under configured worktree root.
6. Record `base_commit` at allocation time.
7. Run agent only inside worktree cwd.
8. Collect diff against `base_commit`.
9. Require handoff before cleanup.
10. Preserve or clean worktree based on `cleanup_policy` and operator decision.
11. Never merge automatically.

## Allocation record contract

| Field | Type | Purpose |
|-------|------|---------|
| `allocation_id` | string | Unique allocator record id |
| `run_id` | string | Dispatch run binding |
| `task_id` | string | Task binding |
| `repo_root` | path | Canonical repository root |
| `worktree_root` | path | Configured allocator root (`runtime/dispatch/worktrees/`) |
| `branch_name` | string | Sanitized branch created for run |
| `base_branch` | string | Branch worktree was created from |
| `base_commit` | string | Git SHA at allocation |
| `created_at` | ISO8601 | Allocation timestamp |
| `expires_at` | ISO8601 | TTL for stale detection |
| `status` | enum | Lifecycle status |
| `cleanup_policy` | enum | `preserve_on_failure`, `clean_on_success`, `manual` |
| `rollback_command` | string | Documented git reset/checkout steps |
| `files_changed` | list | Post-run inventory |
| `dirty_before` | bool | Repo dirty flag at allocation |
| `dirty_after` | bool | Worktree dirty flag at completion |

## Status enum

`requested` → `allocated` → `active` → (`completed` | `failed`) → (`preserved` | `cleanup_pending`) → `cleaned`

## Safety invariants

- One run owns one worktree; no sharing across concurrent runs.
- No two active runs share a worktree path.
- File-writing adapters must not execute against main checkout directly.
- Branch names sanitized (alphanumeric, `/`, `-` only; max 120 chars).
- Worktree path must pass `path_is_inside()` against configured root.
- Cleanup never deletes outside allocated worktree root.
- Destructive cleanup requires operator approval when ambiguity exists (uncommitted work, failed handoff).

## Non-goals (Phase 3.3)

- No `git worktree add` implementation.
- No automatic branch push or merge.
- No dashboard "Allocate worktree" button.