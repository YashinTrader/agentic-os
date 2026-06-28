# ADR-0019: Operator-Commanded Execution Only

**Status:** accepted  
**Date:** 2026-06-12  
**Deciders:** composer (implementation), claude (final review pending)

## Context

Phase 3.2 must not introduce autonomous agent scheduling, background dispatch,
or dashboard/orchestrator execution surfaces.

## Decision

1. **No autonomous execution** — no daemon, scheduler, or orchestrator node runs
   dispatch subprocesses.
2. **Explicit operator flags** — `execute_dispatch.py` requires `--dry-run` or
   `--execute`; omitting both exits with error.
3. **Approval recording is separate** — `approve_dispatch.py` writes records only;
   it never executes.
4. **Dashboard read-only** — may show preview, execution request, result, blocked
   reasons, and CLI hints. No Execute, Approve, Launch, or Run MCP controls.
5. **No automatic side effects** — executor never mutates task owner/status,
   never auto-merges, never auto-pushes.

## Consequences

- Execution remains human-operator intentional and auditable.
- Phase 3.3 autonomous scheduling remains out of scope.

## References

- `scripts/execute_dispatch.py`
- `scripts/approve_dispatch.py`
- `dashboard/app.py` dispatch tab