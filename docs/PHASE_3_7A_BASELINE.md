# Phase 3.7A Baseline

**Date:** 2026-06-28  
**Baseline commit:** `d9f203c39c3a85613ef4c7f76e110e3f4734d9c1`  
**Base branch:** `agent/composer/T-PHASE3-6-CODEX-ACTIVATION-READINESS`  
**Canonical repo:** `C:\Users\gabot\agentic-os`

## Verification at baseline (pre-3.7A edits)

| Check | Result |
|-------|--------|
| `python scripts/run_tests.py` | exit 0, **426** tests |
| `python scripts/validate.py` | exit 0 |
| Repository verification | verified (Phase 3.6 closeout) |
| Autonomy level | **Level 1** |
| `codex-restricted` at baseline | `supports_execution: false`, `restricted_candidate` |

## Phase 3.7A scope

- Flip `codex-restricted` to `activation_candidate` with `supports_execution: true`, `execution_scope: canary_only`
- Fifteen-gate activation evaluator with Phase 3.7B authorization requirement
- Activation manifest v2 and human approval request package
- CLI preflight (read-only discovery only)
- Emergency disable CLI
- ADR-0038 through ADR-0041; clerical Claude sign-off on ADR-0034 through ADR-0037

## Out of scope

- Live Codex prompt execution
- Human approval signature or consumption
- Phase 3.7B authorization artifact
- Worktree allocation from canary runner