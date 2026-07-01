# Phase 3.7B Baseline

**Date:** 2026-06-29  
**Baseline commit:** `2fa6424675899cb3d89a6f7f266086751fdf5975`  
**Base branch:** `agent/composer/T-PHASE3-7A-1-EXECUTOR-BYPASS-FIX`  
**Work branch:** `agent/composer/T-PHASE3-7B-CODEX-CANARY-PREFLIGHT`  
**Canonical repo:** `C:\Users\gabot\agentic-os`

## Verification at baseline (pre-3.7B implementation)

| Check | Result |
|-------|--------|
| `python scripts/run_tests.py` | exit 0, **460** tests |
| `python scripts/validate.py` | exit 0 |
| Repository verification | verified (Phase 3.7A.1 closeout) |
| Autonomy level | **Level 1** |
| Generic executor | blocks `codex-restricted` |
| Dedicated canary runner | refuses without Phase 3.7B authorization |
| `phase3_7b_authorization.json` | absent |
| Human approval | not created / not consumed |
| Live Codex canary | not run |

## Phase 3.7B scope (preflight only)

- Read-only Codex CLI inspection (`codex --version`, `--help`, `exec --help`)
- Operator-commanded isolated worktree allocation (Phase 3.4 allocator)
- Deterministic canary contract, context bundle, execution preview
- Human approval request (`awaiting_human_decision`) — does not authorize execution
- Phase 3.7B authorization **template** (`awaiting_human_authorization`) — not activated
- Activation manifest (`awaiting_human_approval`)
- Dry-run gate stack blocked on human approval + Phase 3.7B authorization
- Emergency-disable preflight verification
- Live command preview (no secrets)

## Out of scope

- `codex exec` with prompt
- Live canary run or `docs/codex-canary-*.md` from a real run
- Human approval signature, HMAC, or consumption
- Completed `phase3_7b_authorization.json`
- Merge, push, or deployment from canary worktree