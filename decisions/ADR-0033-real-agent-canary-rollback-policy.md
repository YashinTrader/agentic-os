# ADR-0033: Real-agent canary and rollback policy

- Status: accepted
- Date: 2026-06-22
- Deciders: composer (implementer), pending claude review
- Related: `docs/PHASE_3_5_CODEX_CANARY_PLAN.md`, `scripts/run_codex_canary.py`

## Context

First live real-agent execution requires controlled canary procedure and rollback guidance.

## Decision

1. **Canary script refuses by default** — requires post-activation `supports_execution: true` and `--execute-canary`.
2. **Human approval + allocation** — canary requires signed approval and allocation paths.
3. **No canary in Phase 3.5 implementation** — plan and script only.
4. **Rollback** — preserve worktree; revert via git in worktree; never auto-merge to main.

## Consequences

- Positive: Documented operator path before first live Codex run.
- Negative: Canary remains manual until activation milestone.

## Reviewer sign-off

- [x] composer (implementer)
- [ ] claude (reviewer)