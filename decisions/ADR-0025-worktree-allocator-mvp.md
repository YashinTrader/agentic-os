# ADR-0025: Worktree allocator MVP

- Status: accepted
- Date: 2026-06-20
- Deciders: composer (implementer), pending claude review
- Related: `dispatch/worktree_allocator.py`, `docs/PHASE_3_4_WORKTREE_ALLOCATOR.md`, ADR-0020

## Context

Phase 3.3 designed worktree allocation; Phase 3.2 blocked file-writing execution without worktree. Phase 3.4 must implement a minimal allocator without autonomous invocation.

## Decision

1. **Operator-commanded CLI only** — `scripts/allocate_worktree.py`; never called from executor or scheduler.
2. **Sibling worktree root** — default `<repo-parent>/<repo-name>-worktrees`; override via `AGENTIC_OS_WORKTREE_ROOT`.
3. **File-based registry** — records under `runtime/worktrees/allocations/`.
4. **Git allowlist** — `rev-parse`, `status`, `worktree`, `merge-base`; argv list only, `shell=False`.
5. **Dirty cleanup refused** — uncommitted worktree → `preserved` status; operator must resolve manually.
6. **Gate binding** — file-writing execution requires matching allocation record; no auto-allocation.

## Consequences

- Positive: Isolated file mutations, auditable lifecycle, path containment enforced.
- Negative: Manual allocate step before file-writing runs; disk usage from preserved dirty trees.
- Real adapters remain preview-only until promotion (ADR-0023).