"""Canonical event vocabulary for logs/agent-events.jsonl (ADR-0004 + Phase 2)."""

from __future__ import annotations

# Phase 1.x lifecycle events (ADR-0004)
PHASE_1_EVENT_TYPES = frozenset(
    {
        "task_created",
        "task_assigned",
        "status_changed",
        "handoff_written",
        "reviewed",
        "decision_recorded",
        "blocked",
        "note",
        "error",
    }
)

# Phase 2 operational events — only types with active emitters (ADR-0010 extension)
PHASE_2_EVENT_TYPES = frozenset(
    {
        "discovery_completed",
        "registry_updated",
        "vault_sync_planned",
        "vault_sync_completed",
        "orchestration_planned",
    }
)

# Phase 3.0 preview events (dry-run only — no execution)
PHASE_3_PREVIEW_EVENT_TYPES = frozenset(
    {
        "dispatch_preview_created",
        "dispatch_blocked",
    }
)

# Reserved for Phase 3.2+ execution (documented, not in ALLOWED until emitters exist)
PHASE_3_2_EXECUTION_EVENT_TYPES = frozenset(
    {
        "dispatch_approval_recorded",
        "dispatch_execution_requested",
        "dispatch_started",
        "dispatch_completed",
        "dispatch_failed",
        "dispatch_timed_out",
        "rollback_required",
        "handoff_required",
    }
)

# Legacy / other reserved names (not emitted in Phase 3.1)
RESERVED_EVENT_TYPES = frozenset(
    {
        "validation_passed",
        "review_packet_created",
        "dispatch_approved",
    }
) | PHASE_3_2_EXECUTION_EVENT_TYPES

ALLOWED_EVENT_TYPES = PHASE_1_EVENT_TYPES | PHASE_2_EVENT_TYPES | PHASE_3_PREVIEW_EVENT_TYPES

# Deprecated v1 field `event` — still accepted in historical log lines with warnings.
V1_ALLOWED_EVENTS = frozenset(
    {
        "started",
        "progress",
        "blocked",
        "decision_needed",
        "handoff",
        "finished",
        "error",
    }
)