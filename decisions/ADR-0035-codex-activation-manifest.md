# ADR-0035: Codex activation manifest and two-person gate

- Status: accepted
- Date: 2026-06-28
- Deciders: composer (implementer), pending claude review
- Related: `dispatch/codex_activation.py`, `schemas/codex_activation_manifest.schema.json`, ADR-0032

## Context

Codex activation requires binding reviewed configuration, CLI help, command contract, and canary scope before human approval.

## Decision

1. **Versioned manifest** — JSON under `runtime/dispatch/codex_activation/<id>.json`.
2. **Hash binding** — adapter config, command contract, canary contract, worktree/environment/approval policies.
3. **Two-person gate** — reviewer approval then human HMAC approval (Phase 3.4).
4. **Pre-active cap in 3.6** — manifests stop at `reviewer_approved` or `awaiting_human_approval`.
5. **Canary-only scope** — `maximum_runs: 1`, short expiry, no general activation.

## Consequences

- Positive: Config or CLI drift invalidates stale manifests.
- Negative: Operators must regenerate manifests on contract changes.

## Reviewer sign-off

- [x] composer (implementer)
- [x] claude (reviewer)