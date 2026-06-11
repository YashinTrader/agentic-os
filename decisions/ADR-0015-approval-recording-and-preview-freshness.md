# ADR-0015: Approval recording and preview freshness

- Status: accepted
- Date: 2026-06-11
- Deciders: composer (implementer), claude (reviewer — pending)
- Approval level: reviewer
- Supersedes: none
- Related: ADR-0014, docs/PHASE_3_1_APPROVAL_MODEL.md, dispatch/freshness.py

## Context

Phase 3.2 execution must not run stale commands after preview or adapter context drifts.
Approvals must be explicit, expiring, and bound to the exact preview the operator reviewed.

## Decision

1. **Approval records** are JSON documents with fields defined in
   `docs/PHASE_3_1_APPROVAL_MODEL.md` and validated by `dispatch/approval_contract.py`.
2. **Preview hash** — SHA-256 over canonical JSON of:
   `command`, `cwd`, `scope_paths`, `adapter_id`, `task_id`, `approval_level`,
   `risk_level` (see `compute_preview_hash`).
3. **Stale approval** — If `approval_record.preview_hash != compute_preview_hash(preview)`,
   execution is blocked.
4. **Expiry** — Human and reviewer approvals require `expires_at`; expired records are
   invalid.
5. **Approver rules** — System cannot approve human-level execution; reviewer approval
   suffices for reviewer-level gates.
6. **Preview-only** — Phase 3.0 `dry_run_preview` does not require approval records.
7. **Default TTL** — Human approvals: **30 minutes**; reviewer approvals: **60 minutes**
   (constants in `dispatch/approval_contract.py`; adapters may override in Phase 3.2).
8. **Split validation API** (Phase 3.1 cleanup) — `validate_approval_record_shape` checks
   well-formed records; `evaluate_approval_satisfaction` checks execution approval with
   structured `status` (`none`, `pending`, `approved`, `blocked`, `stale`, `expired`,
   `revoked`, `invalid`).

Phase 3.1 implements validation helpers only — no signing, auth service, or approval UI.

## Consequences

**Positive**

- Prevents "approved yesterday's command" accidents.
- Clear machine-checkable freshness for Phase 3.2 executor.

**Negative**

- Operators must re-approve when preview changes (intentional friction).

## Sign-off

- [x] composer (proposer/implementer)
- [x] claude (reviewer — Phase 3.1 design review 2026-06-11)