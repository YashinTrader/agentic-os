# Phase 3.2.1 — Controlled Executor Hardening Report

**Status:** implemented  
**Branch:** `agent/composer/T-PHASE3-2-1-AND-3-3-DESIGN`

## Hardening items addressed

| ID | Issue | Fix |
|----|-------|-----|
| M1 | `str.startswith` path containment | `dispatch/path_containment.py` with `path_is_inside()` using `Path.resolve()` + `relative_to()` |
| M2 | Preview freshness soft-fail | `dispatch/freshness.py` blocks execution on missing/invalid/stale plan |
| L1 | `supports_execution` inferred | Required validator field; runtime default `false`; only fixture `true` |
| L3 | Silent event emission failure | `event_emit_errors` in `result.json` + per-run `events.jsonl` |

## Files added

- `dispatch/path_containment.py`
- `dispatch/worktree_policy.py`
- `dispatch/freshness.py`
- `dispatch/approval.py`
- `dispatch/executor.py`
- `scripts/execute_dispatch.py`

## Tests added

- `tests/test_worktree_policy.py`
- `tests/test_dispatch_executor.py`
- `tests/test_phase3_2_1_hardening.py`

## Safety verification

- Runtime subprocess: only `dispatch/executor.py`
- Execution-enabled adapter: only `local-python-exec-test`
- Dashboard: no execute/schedule/promote controls for dispatch
- Event types: `dispatch_started`, `dispatch_completed`, `dispatch_failed` added to allowed vocabulary