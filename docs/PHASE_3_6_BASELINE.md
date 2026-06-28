# Phase 3.6 Baseline

**Date:** 2026-06-28  
**Baseline commit:** `2af82a9e7e812e05059b69653583d1c78dfa43b1` (Phase 3.5 Codex restricted adapter)  
**Branch at baseline:** `agent/composer/T-PHASE3-5-CODEX-RESTRICTED-ADAPTER`  
**Canonical repo:** `C:\Users\gabot\agentic-os`

## Verification at baseline

| Check | Result |
|-------|--------|
| `python scripts/run_tests.py` | exit 0, **387** tests |
| `python scripts/validate.py` | exit 0 |
| Autonomy level | **Level 1** |
| `supports_execution: true` | only `local-python-exec-test` |
| `codex-restricted` | `supports_execution: false`, `restricted_candidate` |

## Phase 3.6 scope

- Fix MA1 (`argv[-1] = prompt_arg` overwrote `-o` output path)
- Lock Codex argv contract with regression tests
- CLI compatibility record and evaluator
- Activation manifest schema and validator (pre-active statuses only)
- Documentation-only canary contract (prepared, not executed)
- Human approval checklist for Gabriel (not an approval)
- Rollback and emergency-disable procedures
- ADR-0034 through ADR-0037
- Clerical Claude reviewer sign-offs on ADR-0029 through ADR-0033

## Out of scope

- `supports_execution: true` for Codex
- Live Codex subprocess or canary execution
- Human approval consumption
- Phase 3.7 scheduling