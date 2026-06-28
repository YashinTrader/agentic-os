# ADR-0040: Human authorization record for one-shot canary

- Status: accepted
- Date: 2026-06-28
- Deciders: composer (implementer), pending claude review
- Related: `schemas/codex_human_approval_request.schema.json`, `docs/PHASE_3_7A_HUMAN_APPROVAL_REQUEST.md`

## Context

Gabriel must receive a precise decision package without the request itself authorizing execution.

## Decision

1. Emit `human_approval_request.json` with status `awaiting_human_decision` only.
2. Forbid `signature`, `approval_hmac`, `approved: true`, and fabricated references in Phase 3.7A.
3. Request binds `canary_contract_hash`, `command_contract_hash`, and `reviewed_commit_sha`.
4. Human-signed approval is a separate artifact created only after Claude approves Phase 3.7A.

## Consequences

- Positive: No accidental approval consumption during candidate preparation.
- Negative: Additional handoff step before Phase 3.7B.

## Reviewer sign-off

- [x] composer (implementer)
- [ ] claude (reviewer)