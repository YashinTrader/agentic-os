# Phase 3.4 Hardening Report

**Date:** 2026-06-20  
**Author:** composer  
**Baseline:** `deca717` (306 tests, validator 0)

## Tests added

| Module | Tests | Coverage |
|--------|-------|----------|
| `test_phase3_4_worktree_allocator.py` | 8 | Sanitization, allocate, duplicate block, dirty cleanup refuse, git shell=False |
| `test_phase3_4_worktree_registry.py` | 5 | Save/load, duplicate detection, status transitions |
| `test_phase3_4_approval_signing.py` | 5 | Sign/verify, TTL, stale/wrong_key, legacy upgrade |
| `test_phase3_4_approval_replay.py` | 4 | First claim, double claim, concurrent race, id validation |
| `test_phase3_4_executor_integration.py` | 2 | File-writing without allocation blocks; signed approval passes gate |
| `test_phase3_4_safety_boundaries.py` | 3 | Single execution adapter, no shell=True, dashboard read-only |

**Total new:** 27 tests → **333** expected (306 baseline + 27).

## Safety invariants verified

1. Worktree allocator never auto-invoked from executor or orchestrator
2. Dirty worktree cleanup refused; status transitions to `preserved`
3. Git subprocess in allocator: allowlisted subcommands, `shell=False`
4. HMAC verification required for signed approvals at reviewer/human gates
5. Single-use approval claim before subprocess execute path
6. File-writing execution blocked without explicit allocation record
7. Only `local-python-exec-test` has `supports_execution: true`
8. Runtime subprocess remains only in `dispatch/executor.py`
9. Dashboard has no Execute/Approve/Allocate controls
10. Autonomy Level 1 unchanged

## Known limitations

- HMAC keys are env vars, not OS keyring (design doc mentioned keyring; MVP uses env)
- HMAC proves key possession, not legal identity
- No automatic worktree allocation on execute
- Real agent adapters remain preview-only
- Approval consumed markers are not pruned automatically
- Worktree records under `runtime/worktrees/allocations/` (not `runtime/dispatch/worktrees/` from design doc)

## Remaining risks

- Operator with signing key can sign any bound preview (expected for Level 1)
- Consumed approval files accumulate on disk
- Missing signing env vars block reviewer/human gates (fail-closed)
- Phase 3.4 implementation is staged (uncommitted at doc time); refresh `runtime/unittest_last_run.txt` before handoff

## Verification commands

```bash
python scripts/run_tests.py
python scripts/validate.py
python -m unittest discover -s tests -p "test_phase3_4*.py"
```