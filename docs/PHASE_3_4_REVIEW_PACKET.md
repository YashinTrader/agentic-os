# Phase 3.4 Review Packet

**Milestone:** Worktree allocator + signed approval + executor integration MVP  
**Baseline:** `deca717` (Phase 3.3.2 closeout)  
**Reviewer:** Claude (final)

## Summary

Phase 3.4 implements operator-commanded worktree allocation, HMAC-SHA256 approval signing, single-use anti-replay, and executor/gate integration. No autonomous execution. No real agent adapters enabled.

## Implementation evidence

| Area | Files |
|------|-------|
| Worktree allocator | `dispatch/worktree_allocator.py`, `dispatch/worktree_registry.py`, `scripts/allocate_worktree.py`, `scripts/cleanup_worktree.py`, `scripts/inspect_worktree.py` |
| Approval signing | `dispatch/approval_signing.py`, `scripts/sign_approval.py`, `scripts/verify_approval.py` |
| Anti-replay | `dispatch/approval_replay.py`, `dispatch/atomic_io.py` |
| Gate + executor | `dispatch/execution_gate.py`, `dispatch/executor.py`, `scripts/execute_dispatch.py` |
| Schemas | `schemas/worktree_allocation_record.schema.json`, `schemas/signed_approval_record.schema.json` |
| Events | `protocol/event_types.py` |
| Tests | `tests/test_phase3_4_*.py` (27 tests) |
| ADRs | ADR-0025 through ADR-0028 |

## Phase 3.4.1 integrity closeout (2026-06-22)

Claude verdict: **APPROVE WITH CHANGES**. Closeout addresses F1 (artifact SHA), F2 (`decisions/**` allowlist removal), F3 (artifact cross-check + validator-at-HEAD). **366** tests after closeout.

| Fix | Evidence |
|-----|----------|
| F1 | `runtime/unittest_last_run.txt` regenerated at `implementation_sha` |
| F2 | `POST_TEST_ALLOWLIST_EXACT` — no `decisions/**` |
| F3 | `verify_repository_verification.py` cross-checks artifact + runs validator |

## Safety checklist for reviewer

- [ ] Only `local-python-exec-test` has `supports_execution: true`
- [ ] Subprocess only in `dispatch/executor.py` (production)
- [ ] No dashboard execute/approve/allocate buttons
- [ ] Worktree allocation is CLI-only (not auto on execute)
- [ ] Dirty worktree cleanup refused
- [ ] HMAC documented as key possession, not legal identity
- [ ] Single-use approval enforced before subprocess
- [ ] Autonomy Level 1 unchanged
- [ ] No scheduler daemon introduced
- [ ] Tests and validator pass

## Verification commands

```bash
python scripts/run_tests.py
python scripts/validate.py
python -m unittest discover -s tests -p "test_phase3_4*.py"
```

## Recommended verdict criteria

**APPROVE** if 306+ tests pass, Phase 3.4 tests pass, validator exits 0, safety grep clean.  
**APPROVE WITH CHANGES** if documentation or artifact gaps only.  
**REJECT** if real adapters enabled, auto-allocation on execute, or autonomous dispatch introduced.