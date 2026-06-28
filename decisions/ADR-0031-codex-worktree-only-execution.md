# ADR-0031: Codex worktree-only execution

- Status: accepted
- Date: 2026-06-22
- Deciders: composer (implementer), pending claude review
- Related: `dispatch/codex_adapter.py`, ADR-0025, ADR-0020

## Context

Codex may write repository files. Canonical main checkout must not be mutated by agent execution.

## Decision

1. **Allocation required** — valid Phase 3.4 record with matching task/run/base SHA.
2. **cwd inside worktree** — Codex `-C` targets allocated worktree only.
3. **Scope containment** — writable paths must resolve inside worktree.
4. **No auto lifecycle** — adapter never allocates, merges, pushes, or deletes worktrees/branches.
5. **Preserve for review** — post-execution worktree retained.

## Consequences

- Positive: File mutations isolated and reviewable before any merge decision.
- Negative: Three operator steps remain: allocate, approve, execute (when activated).

## Reviewer sign-off

- [x] composer (implementer)
- [ ] claude (reviewer)