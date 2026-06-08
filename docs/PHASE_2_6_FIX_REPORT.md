# Phase 2.6 Fix Report

Task: `T-CLAUDE-PHASE2-FIXES`  
Date: 2026-06-07  
Reviewer input: `docs/REVIEW_CLAUDE_PHASE_2.md` — **APPROVE WITH CHANGES**

## Claude review summary

- Phase 2 architecture approved for merge; Phase 3 **design only** until gates land.
- Two high-priority fixes required before any dispatch work: **H1 risk gate**, **H2 event vocabulary**.
- No critical blockers for Phase 2.5 merge.

## H1 fix — risk-gate precedence

**Problem:** `READ_ONLY_KEYWORDS` short-circuited before `HUMAN_KEYWORDS`; `requires_human_approval: true` only escalated when secondary regex matched.

**Fix:** Rewrote `orchestrator/risk.py` with explicit precedence:

1. `blocked` (task status or blocked keywords)
2. `human` (`requires_human_approval`, `risk_level: high`, or human-risk keywords)
3. `reviewer` (reviewer keywords or `risk_level: medium`)
4. `none` (read-only keywords or low risk)

Read-only/dry-run text no longer downgrades human-risk tasks.

**Tests added:** 14 cases in `tests/test_risk_gate.py` including dry-run+deploy, read-only+secrets, flag-only human, high-risk benign text.

## H2 fix — event vocabulary drift

**Problem:** Canonical types declared but emitters used `note` or nothing.

**Fix:**

| Emitter | Event type |
|---------|------------|
| `daemon/registry_writer.py` | `discovery_completed` (success), `error` (failure) |
| `scripts/sync_obsidian.py` | `vault_sync_planned` (dry-run), `vault_sync_completed` (real), `error` (failure) |
| `orchestrator/persistence.py` | `orchestration_planned` (unchanged) |

- Added `protocol/emit_event.py` shared helper.
- Added `error` to canonical vocabulary.
- Removed unused `validation_passed` / `review_packet_created` from validator set (documented as reserved).
- Tests in `tests/test_phase2_6_events.py`.

## Tests added

| Module | Count |
|--------|-------|
| `tests/test_risk_gate.py` | 14 |
| `tests/test_phase2_6_events.py` | 6 |

## Validator result

```
Validation passed.
```

Historical v1 `event` field lines warn only (unchanged).

## Remaining risks

| Risk | Notes |
|------|-------|
| Keyword heuristics | Improved precedence; not full NLP |
| `registry_updated` reserved | No emitter yet — intentional |
| LangGraph dependency | Unchanged |
| Phase 3 execution | Still blocked by ADR-0012 |

## Phase 3 design

Created `docs/PHASE_3_DESIGN_SPEC.md` — dispatch lifecycle, adapter schema, dry-run preview, gates, phased deliverables 3.0–3.2+.

**Phase 3 design can begin.** Phase 3 **implementation** remains blocked until ADR-0012 gates E2–E6 are built with tests.