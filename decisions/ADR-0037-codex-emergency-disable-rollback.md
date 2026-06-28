# ADR-0037: Codex emergency-disable and rollback policy

- Status: accepted
- Date: 2026-06-28
- Deciders: composer (implementer), pending claude review
- Related: `docs/PHASE_3_6_CODEX_ROLLBACK.md`, `dispatch/codex_canary_gates.py`

## Context

Real-agent canaries require operator stop controls and evidence preservation.

## Decision

1. **Emergency flag** — `runtime/dispatch/codex_emergency_disable.json` blocks canary gate 12.
2. **Immediate disable** — `supports_execution: false` + manifest `suspended`/`revoked`.
3. **Evidence preservation** — worktrees, logs, manifests retained.
4. **Canary rollback** — no merge means canonical repo unchanged; optional removal of canary doc after review.
5. **Failure triggers** — unexpected file changes, deletions, timeout, contract drift.

## Consequences

- Positive: Fast stop without destroying audit trail.
- Negative: Manual cleanup of worktrees after incidents.

## Reviewer sign-off

- [x] composer (implementer)
- [ ] claude (reviewer)