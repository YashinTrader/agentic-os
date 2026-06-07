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
    }
)

# Phase 2 operational events (ADR-0010 extension)
PHASE_2_EVENT_TYPES = frozenset(
    {
        "discovery_completed",
        "registry_updated",
        "vault_sync_planned",
        "vault_sync_completed",
        "orchestration_planned",
        "validation_passed",
        "review_packet_created",
    }
)

ALLOWED_EVENT_TYPES = PHASE_1_EVENT_TYPES | PHASE_2_EVENT_TYPES

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