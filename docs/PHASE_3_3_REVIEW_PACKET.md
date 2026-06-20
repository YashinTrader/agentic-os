# Phase 3.3 Review Packet

**Milestone:** Phase 3.2.1 hardening + Phase 3.3 design  
**Branch:** `agent/composer/T-PHASE3-2-1-AND-3-3-DESIGN`  
**Reviewer:** Claude (final)

## Summary

Phase 3.2.1 hardens the controlled subprocess executor. Phase 3.3 delivers design-only artifacts for worktree allocation, approval authenticity, scheduling boundaries, adapter promotion, and runtime governance.

## Phase 3.2.1 changes

| Area | Evidence |
|------|----------|
| Path containment | `dispatch/path_containment.py`, `tests/test_worktree_policy.py` |
| Preview freshness blocking | `dispatch/freshness.py`, executor integration |
| `supports_execution` schema | `agents/adapter_registry.yaml`, `scripts/validate.py` |
| Event emit observability | `dispatch/executor.py` → `event_emit_errors` |

## Phase 3.3 design artifacts

| Document | Purpose |
|----------|---------|
| `docs/PHASE_3_3_WORKTREE_ALLOCATOR_DESIGN.md` | Worktree lifecycle contract |
| `docs/PHASE_3_3_APPROVAL_AUTHENTICITY_DESIGN.md` | Signing and anti-replay |
| `docs/PHASE_3_3_SCHEDULING_BOUNDARIES.md` | Autonomy levels 0–4 |
| `docs/PHASE_3_3_AGENT_ADAPTER_PROMOTION.md` | Promotion checklist |
| `docs/PHASE_3_3_RUNTIME_GOVERNANCE.md` | Concurrency, sessions, monitoring |
| `docs/PHASE_3_3_DESIGN_SPEC.md` | Umbrella spec |
| ADR-0020 through ADR-0024 | Decision records |
| `schemas/*.schema.json` | Pure validation schemas |

## Safety checklist for reviewer

- [ ] Only `local-python-exec-test` has `supports_execution: true`
- [ ] Only `dispatch/executor.py` uses runtime subprocess
- [ ] No dashboard execute/schedule/promote buttons
- [ ] No worktree allocator implementation
- [ ] No signing implementation
- [ ] No scheduler daemon
- [ ] Autonomy level remains 1
- [ ] Tests and validator pass

## Verification commands

```bash
python scripts/run_tests.py
python scripts/validate.py
```

## Recommended verdict criteria

**APPROVE** if all hardening tests pass, design docs complete, and safety grep clean.  
**APPROVE WITH CHANGES** if documentation gaps only.  
**REJECT** if real adapters enabled or autonomous execution introduced.