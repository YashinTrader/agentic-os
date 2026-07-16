# Composer self-review: Claude Reviewer Adapter

## Implemented

- Headless Claude Code adapter with restricted tools and `dontAsk`
- Strict JSON verdict schema and validation
- Idempotent review requests + concurrency-1 review leases
- Deterministic verdict application via assignment channel
- Supervisor integration (`--agents …,claude-reviewer`)
- Dashboard read-only review visibility
- Unit tests with fake Claude executable (15 OK)

## Live preflight (2026-07-16)

- Claude Code **2.1.150** at npm shim path
- Non-interactive probe returned **401 OAuth token revoked**
- Classified as `blocked_authentication` (not mocked as success)
- `ANTHROPIC_API_KEY` unset → API mode unavailable

## Residual risk

Until Gabriel re-authenticates Claude Code (`claude auth login`), live autonomous review cannot complete. Builder results correctly remain `awaiting_review`.
