# ADR-0016: Worktree sandbox before file-writing execution

- Status: accepted
- Date: 2026-06-11
- Deciders: composer (implementer), claude (reviewer — pending)
- Approval level: reviewer
- Supersedes: none
- Related: ADR-0012, ADR-0014, docs/PHASE_3_1_WORKTREE_SANDBOX_STRATEGY.md

## Context

Several adapters (`writes_files: true`) may modify repository files. Executing them on
the main branch without isolation violates ADR-0012 sandbox gates and increases rollback
cost.

## Decision

1. **File-writing dispatch** requires a worktree or dedicated branch before Phase 3.2
   execution (`worktree_required: true` on `ExecutionRequest`).
2. **Contract enforcement** — `validate_execution_request_contract` blocks when
   `writes_files=true` and `worktree_required=false`.
3. **Pre-execution snapshot** — Phase 3.2 executor must record snapshot metadata in
   `rollback.md` before file-writing runs.
4. **Main branch** — Dispatch must never auto-merge or mutate `main` (hard invariant).
5. **Phase 3.1** documents and validates policy only — no worktree creation code.

Read-only adapters may use `repo_root` cwd when `writes_files: false`.

## Consequences

**Positive**

- Aligns dispatch execution with git-isolated agent workflows.
- Reduces risk of unreviewed commits on main.

**Negative**

- Phase 3.2 executor must integrate git worktree tooling (complexity).

## Sign-off

- [x] composer (proposer/implementer)
- [ ] claude (reviewer)