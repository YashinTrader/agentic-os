# Phase 3.4 Baseline

**Date:** 2026-06-20  
**Baseline commit:** `deca7170bd5ee77e04b8a6ec2afe781ebd74cb35` (`deca717` — Phase 3.3.2 closeout handoff)  
**Canonical repo:** `C:\Users\gabot\agentic-os`

## What the baseline contains

- Phase 3.2 controlled executor MVP (dry-run + narrow `--execute`)
- Phase 3.2.1 hardening (path containment, preview freshness blocking)
- Phase 3.3 design artifacts and ADR-0020 through ADR-0024
- Unsigned Phase 3.2 approval records; no worktree allocator implementation

## Verification at baseline

| Check | Result |
|-------|--------|
| `python scripts/run_tests.py` | exit 0, **306** tests |
| `python scripts/validate.py` | exit 0 (v1 event warnings only) |
| Autonomy level | **Level 1** (explicit operator execution) |
| `supports_execution: true` | only `local-python-exec-test` |

Artifact: `runtime/unittest_last_run.txt` (commit `1ee1db9`, 306 tests) predates Phase 3.4 implementation; baseline HEAD is `deca717`.

## Phase 3.4 scope (this milestone)

Implements MVP from Phase 3.3 design:

- Operator-commanded Git worktree allocator (`dispatch/worktree_allocator.py`)
- HMAC-SHA256 signed approvals (`dispatch/approval_signing.py`)
- Single-use approval anti-replay (`dispatch/approval_replay.py`)
- Executor and gate integration (`dispatch/executor.py`, `dispatch/execution_gate.py`)

## Out of scope (unchanged)

- No autonomous scheduling or background dispatch
- No real agent adapters enabled for execution
- No dashboard execute/approve/allocate controls
- HMAC proves **key possession**, not legal identity or non-repudiation

## Post-implementation test delta

Phase 3.4 adds **27** tests (`test_phase3_4_*.py`). Expected total: **333** tests (306 + 27).