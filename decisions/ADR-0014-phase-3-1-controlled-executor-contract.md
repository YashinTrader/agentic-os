# ADR-0014: Phase 3.1 controlled executor contract (design only)

- Status: accepted
- Date: 2026-06-11
- Deciders: composer (implementer), claude (reviewer — pending)
- Approval level: reviewer
- Supersedes: none
- Related: ADR-0012, ADR-0013, docs/PHASE_3_1_EXECUTOR_DESIGN.md

## Context

Phase 3.0 delivers dry-run dispatch preview without execution. Phase 3.2 would add
real agent invocation — a high-risk step that requires a documented contract before any
runtime code lands.

## Decision

Phase 3.1 defines the **controlled executor contract** but does **not** implement
execution:

- `dispatch/executor_contract.py` — types, `validate_execution_request_contract`,
  CLI inventory gate helper
- `dispatch/approval_contract.py` — approval record validation
- `dispatch/freshness.py` — preview hash and staleness
- Design docs and JSON schemas
- Tests for contracts and safety invariants

**Prohibited in Phase 3.1:**

- subprocess / os.system / agent / MCP / LLM API execution
- Dashboard execute/approve buttons
- Task owner/status mutation by dispatch
- Autonomous dispatch loops

Phase 3.2 may implement an executor **only after** separate review of ADR-0014/0015/0016
and an explicit implementation task.

## Consequences

**Positive**

- Phase 3.2 implementers have typed contracts and tests before writing runtime code.
- Validator and preview layers can reuse the same gate vocabulary.

**Negative**

- No end-to-end execution demo until Phase 3.2.

**Neutral**

- Phase 3.0 preview remains the operator-facing dry-run surface.

## Sign-off

- [x] composer (proposer/implementer)
- [ ] claude (reviewer)