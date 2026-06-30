# ADR-0042: Canary-only adapters require dedicated execution route

- Status: accepted
- Date: 2026-06-29
- Deciders: composer (implementer), pending claude review
- Related: `dispatch/execution_route_policy.py`, `dispatch/execution_gate.py`, `scripts/run_codex_canary.py`

## Context

Claude Phase 3.7A review (H1) found that `codex-restricted` with `supports_execution: true` could be reached through the generic `execute_dispatch.py` path while the fifteen-gate canary stack and Phase 3.7B authorization lived only in `run_codex_canary.py`. Absent human approval prevented immediate exploitation, but the bypass would become reachable once Phase 3.7B artifacts exist.

## Decision

1. Introduce `dispatch/execution_route_policy.py` with `evaluate_execution_route()` as the single pure policy helper for execution routing.
2. Generic dispatch (`ROUTE_GENERIC_DISPATCH`) must reject adapters declaring any of: `execution_scope: canary_only`, `dedicated_runner_required: true`, `phase3_7b_authorization_required: true`, `promotion_state: activation_candidate`, or a non-generic `required_execution_route`.
3. `codex-restricted` may execute only through `ROUTE_CODEX_CANARY` via `scripts/run_codex_canary.py`.
4. Route policy is evaluated before approval consumption, anti-replay claim, subprocess, or worktree mutation in the generic executor.
5. Phase 3.7B authorization is necessary but not sufficient to run Codex through generic dispatch; the dedicated route remains mandatory.

## Consequences

- Positive: Defense-in-depth closes H1 before any Phase 3.7B human approval is recorded.
- Positive: `supports_execution: true` alone cannot bypass canary-only routing.
- Negative: Additional adapter metadata (`required_execution_route`, `dedicated_runner_required`) must stay consistent across registry and dedicated YAML.

## Reviewer sign-off

- [x] composer (implementer)
- [ ] claude (reviewer)