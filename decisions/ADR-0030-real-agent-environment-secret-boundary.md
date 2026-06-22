# ADR-0030: Real-agent environment and secret boundary

- Status: accepted
- Date: 2026-06-22
- Deciders: composer (implementer), pending claude review
- Related: `dispatch/agent_environment.py`, ADR-0026

## Context

Real-agent CLIs often inherit broad parent environments containing unrelated credentials.

## Decision

1. **Explicit allowlist** — construct minimal env from named variables only.
2. **Explicit denylist** — HMAC keys, cloud tokens, database URLs, payment keys excluded.
3. **Name-only previews** — previews and logs list `environment_variable_names`, never values.
4. **Fail closed** — if required auth vars absent after filtering, block activation path.

## Consequences

- Positive: Reduces accidental secret exfiltration to agent subprocesses.
- Negative: Operators must ensure Codex auth vars are present in allowlisted names.

## Reviewer sign-off

- [x] composer (implementer)
- [ ] claude (reviewer)