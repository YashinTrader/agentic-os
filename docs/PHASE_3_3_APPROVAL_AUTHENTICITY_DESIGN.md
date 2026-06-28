# Phase 3.3 — Approval Authenticity and Signing Design

**Status:** design only — no cryptographic implementation in Phase 3.3

## Problem

Phase 3.2 approval records are local JSON files with no authenticity guarantees. An attacker or misconfigured tool could replay, transplant, or forge approvals.

## Approval record extensions (future)

| Field | Purpose |
|-------|---------|
| `approval_id` | Unique approval identifier |
| `approver_identity` | Human operator id (never `system`) |
| `provenance` | How approval was captured (CLI, dashboard, signed file) |
| `preview_hash` | SHA-256 of canonical preview JSON |
| `plan_hash` | Bound to live plan at approval time |
| `command_hash` | SHA-256 of resolved command string |
| `cwd_hash` | Bound working directory |
| `scope_hash` | Bound scope_paths |
| `adapter_id` | Adapter binding |
| `nonce` | Anti-replay per run |
| `issued_at` / `expires_at` | Temporal bounds |
| `revoked_at` | Revocation timestamp |
| `signature` | Optional HMAC or asymmetric signature |

## Options compared

| Option | Pros | Cons | MVP fit |
|--------|------|------|---------|
| Local operator confirmation JSON | Simple, auditable in git | Forgeable, replayable | Current Phase 3.2 |
| HMAC with local secret | Fast, offline | Secret storage risk | Good MVP+1 |
| Asymmetric signature | Non-repudiation | Key management | Phase 3.4+ |
| OS keyring-backed approval | Uses platform trust | Platform-specific | Optional enhancement |
| Git-signed approval commit | Git-native audit trail | Heavy UX | High-risk promotions |

## Recommended MVP path

1. **Phase 3.2 (current):** Operator JSON with field binding (run_id, task_id, adapter_id, command, cwd).
2. **Phase 3.4:** HMAC-SHA256 over canonical approval payload using key from OS keyring (`AGENTIC_OS_APPROVAL_KEY`), never stored in repo.
3. **Phase 3.5+:** Optional GPG signature for high-risk adapter promotions.

## Hard rules

- System/automated approvals can never satisfy `human` approval level.
- Approvals cannot transfer between previews (preview_hash binding).
- Changed command, cwd, or scope invalidates approval.
- Revoked or expired approvals are invalid.
- Replay to another run/task/adapter is blocked via nonce + binding fields.
- No secrets stored in repository.

## Non-goals (Phase 3.3)

- No signing implementation.
- No keyring integration.
- No dashboard approve button.