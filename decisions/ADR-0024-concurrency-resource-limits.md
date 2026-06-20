# ADR-0024: Concurrency and resource limits

- Status: accepted (design only)
- Date: 2026-06-19
- Deciders: composer (implementer), pending claude review
- Related: `docs/PHASE_3_3_RUNTIME_GOVERNANCE.md`

## Context

Unbounded concurrent agent runs risk resource exhaustion, conflicting writes, and uncontrolled API spend.

## Decision

- Proposed defaults: global concurrency 2, per-agent concurrency 1, one file-writing run per repo.
- Time budget enforced via adapter `timeout_seconds` (implemented in Phase 3.2).
- Token/API budgets tracked manually until provider metering is available.
- Cancellation: SIGTERM → grace → SIGKILL; orphan and stale run detection required in future scheduler.
- Phase 3.3 defines policy only; no enforcement daemon.

## Consequences

- Positive: Framework for safe scaling.
- Negative: Throughput limits for parallel work.