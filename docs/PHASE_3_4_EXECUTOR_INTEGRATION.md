# Phase 3.4 — Executor Integration

**Status:** implemented  
**Autonomy level:** Level 1

## Integration points

Phase 3.4 extends the Phase 3.2 executor without changing the subprocess boundary.

| Change | Location |
|--------|----------|
| Signed approval verification | `dispatch/execution_gate.py` |
| Replay pre-check + claim | `dispatch/execution_gate.py`, `dispatch/executor.py` |
| Allocation record loading | `dispatch/executor.py` (`--allocation-path`, `--allocation-id`) |
| Worktree gate for file-writing | `evaluate_allocation_for_execution()` in gate |
| New events | `protocol/event_types.py` |

## Execution flow (unchanged core)

1. Operator runs `scripts/execute_dispatch.py` with `--dry-run` or `--execute`.
2. Gate evaluates all hard rules (no subprocess in gate).
3. If blocked → `dispatch_blocked`, no subprocess.
4. If dry-run passes → `dispatch_dry_run_completed`, no subprocess.
5. If execute passes → claim approval (if present) → subprocess in `executor.py` only.

## Phase 3.4 gate additions

When `approval_level` is `reviewer` or `human`:

1. `verify_signed_approval(record, preview=preview)` must return `valid`
2. If `check_replay=True` and approval already consumed → blocked

When adapter `writes_files: true` or `worktree_required: true`:

1. `base_sha` required on preview
2. `allocation_record` must match task/run/base_sha
3. `cwd` and `scope_paths` must be inside allocated worktree
4. Missing allocation → blocked ("automatic allocation is not enabled")

## Executor claim sequence

On `--execute` with approval record:

```
try_claim_approval() → success → approval_consumed event → subprocess
                     → failure → approval_replay_blocked event → no subprocess
```

Claim is atomic via `atomic_create_json()`; concurrent claims: one winner.

## CLI additions

`scripts/execute_dispatch.py`:

- `--allocation-path` — JSON allocation record file
- `--allocation-id` — load from registry

Worktree and approval CLIs remain separate from execution (operator-commanded).

## Safety boundaries (preserved)

- Subprocess only in `dispatch/executor.py`
- Only `local-python-exec-test` has `supports_execution: true`
- Dashboard dispatch tab remains read-only
- No orchestrator or daemon dispatch paths

## Events added (Phase 3.4)

- `worktree_allocated`, `worktree_cleanup_blocked`, `worktree_cleaned`
- `approval_signed`, `approval_verified`
- `approval_consumed`, `approval_replay_blocked`