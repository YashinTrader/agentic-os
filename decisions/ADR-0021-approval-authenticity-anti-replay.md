# ADR-0021: Approval authenticity and anti-replay

- Status: accepted (design only)
- Date: 2026-06-19
- Deciders: composer (implementer), pending claude review
- Related: `docs/PHASE_3_3_APPROVAL_AUTHENTICITY_DESIGN.md`, `dispatch/approval_store.py`

## Context

Phase 3.2 uses local JSON approval records without signatures. Replay and transplant attacks are possible if an operator mistakes file paths.

## Decision

- Phase 3.2 bindings: run_id, task_id, adapter_id, command, working_directory.
- Phase 3.4 MVP signing: HMAC-SHA256 over canonical payload with key in OS keyring.
- Anti-replay via nonce + preview_hash + plan_hash + expiry.
- System approvals cannot satisfy human gates.
- No secrets in repository.

## Consequences

- Positive: Clear promotion path for authenticated approvals.
- Negative: Key management burden for operators.
- Phase 3.3 does not implement signing.