# ADR-0022: No autonomous execution by default

- Status: accepted (design only)
- Date: 2026-06-19
- Deciders: composer (implementer), pending claude review
- Related: `docs/PHASE_3_3_SCHEDULING_BOUNDARIES.md`, ADR-0012

## Context

Agentic OS must not silently escalate from preview to autonomous agent swarms. Phase 3.2 introduces explicit operator execution for a test fixture only.

## Decision

- Runtime autonomy level remains **Level 1** until a future ADR explicitly raises it.
- No scheduler daemon, no background dispatch, no auto task pickup.
- Level 2+ requires new ADR, tests, and human review.
- Emergency stop and operator pause are design requirements for future scheduler.

## Consequences

- Positive: Predictable safety boundary for operators.
- Negative: Manual operator steps for each execution.
- Phase 3.3 documents scheduler requirements without implementing them.