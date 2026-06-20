# Phase 3.3 Design Spec — Worktree, Approval Signing, Scheduling Boundaries

**Status:** design only — approved for review, not for implementation  
**Branch:** `agent/composer/T-PHASE3-2-1-AND-3-3-DESIGN`  
**Prerequisite:** Phase 3.2.1 hardening complete

## Scope

Phase 3.3 defines the next operational layer without implementing it:

1. Git worktree allocator contract — `docs/PHASE_3_3_WORKTREE_ALLOCATOR_DESIGN.md`
2. Approval authenticity/signing contract — `docs/PHASE_3_3_APPROVAL_AUTHENTICITY_DESIGN.md`
3. Scheduling and autonomy boundaries — `docs/PHASE_3_3_SCHEDULING_BOUNDARIES.md`
4. Real-agent adapter promotion — `docs/PHASE_3_3_AGENT_ADAPTER_PROMOTION.md`
5. Resource, concurrency, session, monitoring — `docs/PHASE_3_3_RUNTIME_GOVERNANCE.md`

## ADRs (new)

| ID | Title |
|----|-------|
| ADR-0020 | Worktree allocation and lifecycle |
| ADR-0021 | Approval authenticity and anti-replay |
| ADR-0022 | No autonomous execution by default |
| ADR-0023 | Real-agent adapter promotion |
| ADR-0024 | Concurrency and resource limits |

## Optional schemas (pure validation)

- `schemas/worktree_allocation.schema.json`
- `schemas/adapter_promotion.schema.json`
- `schemas/scheduling_policy.schema.json`

## Current runtime posture (unchanged)

- Autonomy Level 1 — explicit operator `execute_dispatch.py --execute`.
- Only `local-python-exec-test` has `supports_execution: true`.
- Only `dispatch/executor.py` performs runtime subprocess execution.
- Dashboard Dispatch tab remains read-only.

## Implementation phases (after Claude review)

| Phase | Deliverable |
|-------|-------------|
| 3.4 | Worktree allocator module |
| 3.4 | HMAC approval signing |
| 3.5 | Queue + Level 2 scheduling |
| 3.6+ | Real adapter promotions per ADR-0023 |

## Non-goals

See scheduling boundaries doc for prohibited autonomous behavior.