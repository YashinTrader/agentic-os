# ADR-0026: HMAC approval authenticity

- Status: accepted
- Date: 2026-06-20
- Deciders: composer (implementer), pending claude review
- Related: `dispatch/approval_signing.py`, `docs/PHASE_3_4_APPROVAL_AUTHENTICITY.md`, ADR-0021

## Context

Phase 3.2 approval records were unsigned JSON. Phase 3.3 designed HMAC signing; Phase 3.4 implements MVP binding.

## Decision

1. **HMAC-SHA256** over canonical JSON payload (version 2 records).
2. **Separate keys** per approver type via env vars (`AGENTIC_OS_REVIEWER_APPROVAL_KEY`, `AGENTIC_OS_HUMAN_APPROVAL_KEY`).
3. **Scope binding** — preview_hash, command hash, cwd, scope_paths, task/run/adapter IDs verified at gate.
4. **Key possession only** — HMAC proves holder of secret signed payload; does not prove legal identity or non-repudiation.
5. **No secrets in repo** — keys supplied by operator environment at sign/verify time.
6. **TTL enforcement** — per-approver maximum TTL at sign time.

## Consequences

- Positive: Tamper and transplant detection for bound previews; clear upgrade from unsigned v1.
- Negative: Key management burden; missing env vars fail-closed at gate.
- Asymmetric signatures deferred to future phase.