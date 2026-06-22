# Phase 3.5 Codex Security Model

## Threat model (Level 1)

- Malicious or mistaken operator command
- Stale or tampered preview/approval
- Secret leakage via environment inheritance
- Filesystem escape outside allocated worktree
- Replay of consumed approvals

## Controls

| Control | Implementation |
|---------|----------------|
| Preview-first | `scripts/preview_codex_dispatch.py` |
| Human HMAC approval | Phase 3.4 `approval_signing.py` |
| Anti-replay | Phase 3.4 `approval_replay.py` |
| Worktree isolation | Phase 3.4 allocator + `codex_adapter.py` gates |
| Environment boundary | `agent_environment.py` allowlist/denylist |
| Execution gate | `supports_execution: false` blocks subprocess |
| Forbidden CLI flags | `--dangerously-bypass-*` blocked in builder and validator |

## Non-goals (Phase 3.5)

- Legal non-repudiation of human approver identity
- Autonomous scheduling
- MCP tool execution