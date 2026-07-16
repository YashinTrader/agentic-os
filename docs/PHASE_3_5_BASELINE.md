# Phase 3.5 Baseline

**Date:** 2026-06-22  
**Baseline commit:** `f39188ab882af99920292adbed136effd1f10ffb` (Phase 3.4.1 integrity closeout)  
**Canonical repo:** `C:\Users\gabot\agentic-os`

## Verification at baseline

| Check | Result |
|-------|--------|
| `python scripts/run_tests.py` | exit 0, **366** tests |
| `python scripts/validate.py` | exit 0 |
| Autonomy level | **Level 1** |
| `supports_execution: true` | only `local-python-exec-test` |

## Phase 3.5 scope

- Codex restricted adapter candidate (`codex-restricted`)
- Command builder, context bundle, environment boundary, result parser
- CLI discovery (`scripts/inspect_codex_cli.py`)
- Preview and canary scripts (canary refuses until activation)
- ADR-0029 through ADR-0033
- ADR-0025–0028 Claude reviewer sign-offs (clerical)

## Out of scope

- `supports_execution: true` for Codex (separate activation task)
- Live Codex subprocess in tests or executor
- Level 2 scheduling
- MCP execution