# ADR-0029: Codex restricted adapter contract

- Status: accepted
- Date: 2026-06-22
- Deciders: composer (implementer), pending claude review
- Related: `agents/codex_restricted_adapter.yaml`, `dispatch/codex_adapter.py`, ADR-0023

## Context

Phase 3.4 established worktree allocation, HMAC approvals, and anti-replay. Phase 3.5 introduces the first real-agent adapter candidate without enabling execution.

## Decision

1. **Separate identity** — `codex-restricted` distinct from `codex-cli-preview`; preview adapter is not promoted.
2. **Candidate state** — `promotion_state: restricted_candidate` with `supports_execution: false`.
3. **Human approval** — `approval_level: human`; reviewer approval insufficient.
4. **Worktree + secrets + network** — all declared true; MCP false.
5. **Command builder only** — `dispatch/codex_adapter.py` constructs argv; no subprocess in adapter module.
6. **Codex exec subcommand** — `workspace-write` sandbox; forbidden danger bypass flags.

## Consequences

- Positive: Real-agent path designed with existing Phase 3.4 gates; activation is a separate clerical step.
- Negative: Operator workflow remains multi-step until activation milestone.

## Reviewer sign-off

- [x] composer (implementer)
- [ ] claude (reviewer)