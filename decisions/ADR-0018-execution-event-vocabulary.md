# ADR-0018: Execution Event Vocabulary

**Status:** accepted  
**Date:** 2026-06-12  
**Deciders:** composer (implementation), claude (final review pending)

## Context

Phase 3.2 executor and approval CLI emit lifecycle events. The validator must
accept only types with active emitters; unknown types are rejected.

## Decision

Add to `ALLOWED_EVENT_TYPES` (active emitters in Phase 3.2):

| Event | Emitter |
|-------|---------|
| `dispatch_requested` | `dispatch/executor.py` |
| `dispatch_dry_run_completed` | `dispatch/executor.py` |
| `dispatch_started` | `dispatch/executor.py` |
| `dispatch_completed` | `dispatch/executor.py` |
| `dispatch_failed` | `dispatch/executor.py` |
| `dispatch_timed_out` | `dispatch/executor.py` |
| `approval_record_created` | `scripts/approve_dispatch.py` |
| `handoff_required` | `dispatch/executor.py` |

Retain Phase 3.0 preview events: `dispatch_preview_created`, `dispatch_blocked`.

Reserved (not allowed until emitters exist): `dispatch_approval_recorded`,
`dispatch_execution_requested`, `rollback_required`, `dispatch_approved`.

Per-run structured log: `runtime/dispatch/runs/<run_id>/events.jsonl` (not validated
by canonical vocabulary).

## Consequences

- Validator and `protocol/emit_event` enforce vocabulary at append time.
- Reserved names cannot be emitted accidentally before implementation.

## References

- `protocol/event_types.py`
- `docs/AGENT_PROTOCOL.md` §6.0.1