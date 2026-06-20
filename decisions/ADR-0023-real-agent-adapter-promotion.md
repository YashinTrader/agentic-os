# ADR-0023: Real-agent adapter promotion process

- Status: accepted (design only)
- Date: 2026-06-19
- Deciders: composer (implementer), pending claude review
- Related: `docs/PHASE_3_3_AGENT_ADAPTER_PROMOTION.md`, `agents/adapter_registry.yaml`

## Context

Only `local-python-exec-test` may have `supports_execution: true`. Promoting Codex, Claude, Composer, Cursor, Gemini, or MCP adapters requires a repeatable safety process.

## Decision

- `supports_execution` is explicit per adapter; default `false`.
- Promotion requires adapter-specific ADR, checklist completion, tests, reviewer sign-off, and human sign-off when high-risk.
- Promotion states: planned → preview_only → test_execution → restricted_execution → active.
- Revocation sets `status: disabled` and `supports_execution: false`.
- No promotions during Phase 3.2.1 or Phase 3.3 design milestone.

## Consequences

- Positive: Prevents accidental real-agent activation.
- Negative: Overhead for each adapter enablement.