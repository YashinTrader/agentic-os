# ADR-0032: Two-stage adapter activation

- Status: accepted
- Date: 2026-06-22
- Deciders: composer (implementer), pending claude review
- Related: `agents/adapter_registry.yaml`, ADR-0023

## Context

Promoting real agents requires implementation validation separate from execution enablement.

## Decision

1. **Stage 1 — candidate** — implement adapter, tests, validator rules; `supports_execution: false`.
2. **Stage 2 — activation** — separate clerical task after Claude approval flips `supports_execution: true`.
3. **Validator coupling** — `promotion_state` must agree with `supports_execution`.
4. **Phase 3.5 scope** — Stage 1 only for `codex-restricted`.

## Consequences

- Positive: Prevents accidental live Codex runs during implementation review.
- Negative: Additional milestone for activation.

## Reviewer sign-off

- [x] composer (implementer)
- [x] claude (reviewer)