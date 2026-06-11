# Phase 3.1 — Worktree / Sandbox Strategy

**Status:** Design only  
**Related:** ADR-0016, `dispatch/executor_contract.py`

## Principles

1. **No file-writing execution on `main`** — File-writing adapters must not execute with
   cwd on the main worktree branch tip without isolation.
2. **Worktree or dedicated branch** — Adapters with `writes_files: true` require
   `worktree_required: true` at execution request validation time.
3. **Read-only adapters** — May run from repo root when `working_directory_policy:
   repo_root` and `writes_files: false` (Phase 3.2 still subject to ADR-0012 gates).
4. **Cwd containment** — Execution cwd must resolve inside repo or worktree root; path
   traversal outside scope is blocked.
5. **Runtime logs** — All dispatch run artifacts under `runtime/dispatch/runs/<run_id>/`
   (gitignored per Phase 3.0.1).
6. **Pre-execution snapshot** — Before any file-writing execution, Phase 3.2 executor must
   record a snapshot reference in `rollback.md`.
7. **Rollback notes required** — `rollback_notes` / `rollback.md` mandatory when
   `writes_files: true`.

## Preview advisory hint (Phase 3.1 cleanup)

Phase 3.0 preview may include `worktree_required: true` when `writes_files: true` or
`working_directory_policy: worktree`. This is **advisory only** — the executor must still
enforce the hard block below.

## Validation (Phase 3.1)

`validate_execution_request_contract` blocks when:

```
writes_files=true AND worktree_required=false
```

## Worktree policy mapping

| `working_directory_policy` | `writes_files` | Phase 3.2 expectation |
|---------------------------|----------------|-------------------------|
| `repo_root` | false | Read-only preview/execution in repo root |
| `repo_root` | true | **Blocked** until worktree allocated |
| `worktree` | true | Execute in isolated git worktree |
| `task_subdir` | false | Scoped to `tasks/` subtree |

## Phase 3.1 scope

- Document strategy and enforce via contract validation.
- **Do not** create git worktrees, branches, or snapshots in Phase 3.1.