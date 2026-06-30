# ADR-0036: Documentation-only first Codex canary

- Status: accepted
- Date: 2026-06-28
- Deciders: composer (implementer), pending claude review
- Related: `dispatch/codex_canary_contract.py`, `docs/PHASE_3_6_CODEX_CANARY_RUNBOOK.md`

## Context

The first live Codex run must prove worktree isolation with minimal blast radius.

## Decision

1. **Single file** — `docs/codex-canary-<run-id>.md` only.
2. **Fixed sentence** — `Codex documentation-only canary confirmed.`
3. **Forbidden** — source/test/CI/adapter changes, git commit/merge/push, MCP.
4. **Contract hash** — `compute_canary_contract_hash()` binds manifests.
5. **Phase 3.6** — contract prepared; run refused until activation.

## Consequences

- Positive: Lowest-risk first proof of Codex path.
- Negative: Does not validate code-editing behavior until later milestone.

## Reviewer sign-off

- [x] composer (implementer)
- [ ] claude (reviewer)