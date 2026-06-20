# ADR-0020: Worktree allocation and lifecycle

- Status: accepted (design only)
- Date: 2026-06-19
- Deciders: composer (implementer), pending claude review
- Related: `docs/PHASE_3_3_WORKTREE_ALLOCATOR_DESIGN.md`, `dispatch/worktree_policy.py`

## Context

File-writing agent adapters must not mutate the main checkout. Phase 3.2.1 adds path containment helpers but does not allocate Git worktrees. Phase 3.3 must define the allocator contract before implementation.

## Decision

- One dispatch run owns one worktree under `runtime/dispatch/worktrees/<run_id>/`.
- Allocation records capture `base_commit`, `branch_name`, and cleanup policy.
- Agents execute only inside allocated worktree cwd when `working_directory_policy: worktree`.
- Cleanup is never automatic for failed runs; operator confirms destructive cleanup.
- No auto-merge to main.

## Consequences

- Positive: Isolated diffs, auditable rollback, safe concurrent planning.
- Negative: Disk usage, manual cleanup for preserved worktrees.
- Phase 3.3 does not implement `git worktree` commands.