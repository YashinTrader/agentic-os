# ADR-0038: Codex canary-only activation state

- Status: accepted
- Date: 2026-06-28
- Deciders: composer (implementer), pending claude review
- Related: `agents/codex_restricted_adapter.yaml`, `dispatch/codex_activation_gate.py`

## Context

Phase 3.6 kept `codex-restricted` disabled (`supports_execution: false`). Phase 3.7A must prepare the exact activation candidate configuration while blocking live execution.

## Decision

1. Set `promotion_state: activation_candidate` with `supports_execution: true` and `execution_scope: canary_only`.
2. Cap at `maximum_runs: 1` with `automatic_disable_after_run: true`.
3. Require `live_run_authorized: false` and `phase3_7b_authorization_required: true` on the adapter.
4. Fifteen layered gates in `evaluate_activation_gates()` must pass before any Codex subprocess is reachable.

## Consequences

- Positive: Activation package reflects production candidate state for Claude review.
- Negative: Registry now lists two execution-capable adapters; Codex remains canary-only.

## Reviewer sign-off

- [x] composer (implementer)
- [x] claude (reviewer)