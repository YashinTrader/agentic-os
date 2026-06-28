# ADR-0027: Single-use approval anti-replay

- Status: accepted
- Date: 2026-06-20
- Deciders: composer (implementer), claude (reviewer — Phase 3.4.1 closeout 2026-06-20)
- Related: `dispatch/approval_replay.py`, `dispatch/executor.py`, ADR-0021

## Context

Signed approvals could still be replayed for a second subprocess if only signature validity were checked.

## Decision

1. **Atomic claim** — `try_claim_approval()` creates `runtime/dispatch/approval_consumed/<approval_id>.json` via `atomic_create_json`.
2. **Claim before subprocess** — executor claims immediately before `subprocess.run` on `--execute` path.
3. **Gate pre-check** — `check_replay=True` blocks already-consumed approvals during gate evaluation.
4. **Events** — emit `approval_consumed` on success, `approval_replay_blocked` on failure.
5. **One approval, one execution** — second attempt with same `approval_id` is rejected.

## Consequences

- Positive: Prevents naive replay of valid signatures across multiple runs.
- Negative: Consumed markers accumulate; operator must manage disk; approval cannot be reused after failed claim mid-flight without new approval.
- Does not prevent holder of signing key from issuing new approvals (Level 1 expectation).

## Reviewer sign-off

- [x] composer (implementer)
- [x] claude (reviewer — Phase 3.4.1 closeout 2026-06-20)