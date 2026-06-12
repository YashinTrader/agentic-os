# ADR-0017: Phase 3.2 Controlled Executor MVP

**Status:** accepted  
**Date:** 2026-06-12  
**Deciders:** composer (implementation), claude (final review pending)

## Context

Phase 3.1 defined executor contracts without execution. Phase 3.2 introduces the
first operator-commanded executor path with strict safety gates.

## Decision

1. Add `dispatch/executor.py` as the **only** production module that may invoke
   `subprocess` for dispatch.
2. Execution is allowed only via explicit CLI:
   `python scripts/execute_dispatch.py --preview <path> --execute [--approval <path>]`
3. Dry-run executor path validates all gates without subprocess:
   `--dry-run`
4. Only adapters with `supports_execution: true` may run subprocess; all other
   adapters remain preview-only.
5. Phase 3.2 MVP ships one safe fixture adapter: `local-python-exec-test`.

## Consequences

- Operators gain a gated, logged, timeout-bounded execution path for safe tests.
- Real agent adapters (Codex, Claude, Gemini, Composer CLI) remain preview-only.
- Dashboard and orchestrator must not execute dispatch.

## References

- `docs/PHASE_3_2_EXECUTOR_MVP.md`
- `dispatch/execution_gate.py`
- `dispatch/executor.py`