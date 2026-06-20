# Phase 3.2.1 — Controlled Executor Hardening Report

**Status:** implemented (canonical rebuild on Phase 3.2 base `5579146`)  
**Branch:** `agent/composer/T-PHASE3-2-1-AND-3-3-DESIGN` → review fixes on `agent/composer/T-PHASE3-3-REVIEW-FIXES`  
**Reviewed base before fixes:** `b7a1239b4e429dd6c903433c6ed773ab71a03c95`

## Hardening items addressed

| ID | Issue | Fix |
|----|-------|-----|
| M1 | `str.startswith` path containment | `dispatch/path_containment.py` with `path_is_inside()` using `Path.resolve()` + `relative_to()` |
| M2 | Preview freshness soft-fail | `dispatch/execution_gate.py` blocks `--execute` when plan/task context cannot be verified; warns on `--dry-run` |
| L1 | `supports_execution` inferred | Required validator field; runtime default `false`; only fixture `true` |
| L3 | Silent event emission failure | `event_emit_errors` in `result.json` + per-run `events.jsonl` |

## Files changed in canonical rebuild

- `dispatch/path_containment.py` (new)
- `dispatch/worktree_policy.py` (path_is_inside wiring)
- `dispatch/execution_gate.py` (M2 execute-path block)
- `dispatch/executor.py` (L3 event_emit_errors)
- `dispatch/runtime_capture.py` (`ExecutionResult.event_emit_errors`)
- `scripts/validate.py` (`supports_execution` required)
- `agents/adapter_registry.yaml` (explicit boolean on all adapters)
- `scripts/execute_dispatch.py` (stderr warning on emit failures)

Phase 3.1 modules reused unchanged: `dispatch/freshness.py`, `dispatch/approval_store.py`, `dispatch/approval_contract.py`.

## Tests

| Module | Coverage |
|--------|----------|
| `tests/test_path_containment.py` | M1 path containment |
| `tests/test_dispatch_worktree_policy.py` | Worktree policy integration |
| `tests/test_phase3_2_1_hardening.py` | L1 validator + subprocess boundary |
| `tests/test_dispatch_execution_gate.py` | Gate rules including freshness |
| `tests/test_dispatch_executor.py` | Executor dry-run/execute paths |
| `tests/test_phase3_3_review_fixes.py` | M2/L3 review-fix regressions (Phase 3.3.1) |

## Test counts

- Phase 3.2 baseline: **262**
- Recovered branch before review fixes: **280**
- After Phase 3.3.1 regressions: **296** (see `runtime/unittest_last_run.txt` on the review-fixes branch)

## Safety verification

- Runtime subprocess: only `dispatch/executor.py`
- Execution-enabled adapter: only `local-python-exec-test`
- Dashboard: no execute/schedule/promote controls for dispatch
- Event types: Phase 3.2 execution vocabulary unchanged (ADR-0018)