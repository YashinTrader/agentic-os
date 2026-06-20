# Phase 3.3 — Real-Agent Adapter Promotion Process

**Status:** design only — no promotions in Phase 3.3

## Goal

Define how an adapter moves from `supports_execution: false` to `supports_execution: true` without accidental activation of Codex, Claude, Gemini, Composer, Cursor, OpenClaw, or MCP adapters.

## Promotion states

`planned` → `preview_only` → `test_execution` → `restricted_execution` → `active` → (`disabled` | `revoked`)

## Required checklist (every real adapter)

1. Adapter-specific ADR.
2. Explicit `allowed_commands` list.
3. `forbidden_args` / forbidden token policy.
4. CLI inventory validation against `runtime/registry/cli_inventory.yaml`.
5. Declared `timeout_seconds`.
6. `working_directory_policy` and scope rules.
7. `writes_files` declaration with rollback plan.
8. Worktree requirement when `writes_files: true`.
9. Network access declaration.
10. Secrets declaration (metadata only; no repo secrets).
11. MCP declaration (must be false for CLI adapters).
12. Dry-run preview tests.
13. Safe fixture/integration tests in isolated worktree.
14. Documented rollback procedure.
15. Reviewer sign-off (Claude or designated reviewer).
16. Human sign-off for high-risk adapters.

## Current registry posture

| Adapter | supports_execution |
|---------|-------------------|
| local-python-exec-test | `true` (fixture only) |
| composer-cli-preview | `false` |
| codex-cli-preview | `false` |
| claude-cli-preview | `false` |
| cursor-cli-preview | `false` |
| blocked-mcp-preview | `false` |

## Promotion gate

Changing `supports_execution` to `true` requires:

- PR with ADR reference.
- Updated tests proving gates still block without approval.
- Explicit reviewer approval in handoff.
- No dashboard toggle.

## Revocation

Set `status: disabled` and `supports_execution: false`. Emit `dispatch_blocked` if execution attempted.