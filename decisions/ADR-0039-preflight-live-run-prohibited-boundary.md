# ADR-0039: Preflight-complete but live-run-prohibited boundary

- Status: accepted
- Date: 2026-06-28
- Deciders: composer (implementer), pending claude review
- Related: `scripts/run_codex_canary.py`, `docs/PHASE_3_7A_LIVE_RUN_PROHIBITION.md`

## Context

Phase 3.7A completes CLI preflight, manifest, and human approval request without authorizing a live Codex prompt.

## Decision

1. Phase 3.7A manifest statuses limited to `awaiting_claude_review` or `awaiting_human_approval`.
2. `phase3_7b_authorization.json` must be absent; runner refuses with a fixed blocked reason.
3. `run_codex_canary.py` always exits 3 with `codex_subprocess_invoked: false`.
4. No approval consumption while Phase 3.7B authorization is absent.

## Consequences

- Positive: Clear milestone boundary before first live canary.
- Negative: Operators must complete two review gates (Claude 3.7A, human 3.7B) before execution.

## Reviewer sign-off

- [x] composer (implementer)
- [ ] claude (reviewer)