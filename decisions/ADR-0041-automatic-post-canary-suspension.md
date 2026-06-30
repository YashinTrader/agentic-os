# ADR-0041: Automatic post-canary suspension policy

- Status: accepted
- Date: 2026-06-28
- Deciders: composer (implementer), pending claude review
- Related: `dispatch/codex_activation_gate.py`, `agents/codex_restricted_adapter.yaml`

## Context

The first Codex canary is a one-shot experiment requiring automatic suspension afterward.

## Decision

1. After `runs_consumed >= maximum_runs`, status transitions to `suspended_pending_review`.
2. `second_attempt_blocked` and `automatic_retry_allowed: false` in post-canary evaluation.
3. `supports_execution` source configuration unchanged; suspension is runtime/manifest state.
4. Emergency disable via `scripts/disable_codex_canary.py` writes `disabled.json` only.

## Consequences

- Positive: Prevents silent second canary without new approval cycle.
- Negative: Re-activation requires full review path again.

## Reviewer sign-off

- [x] composer (implementer)
- [ ] claude (reviewer)