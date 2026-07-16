# Autonomous Loop Layers (Execution vs Notification)

**Date:** 2026-07-16  
**Status:** Active contract for Agentic OS

The autonomous builder loop uses **two separate layers**. Both must stay enabled.

| Layer | Responsibility | Evidence | Not evidence of |
|-------|----------------|----------|-----------------|
| **Execution** (physical supervisor) | Consume `--wake`, claim capacity, launch agent process | PID, run state, stdout/stderr under `runtime/dispatch/runs/` | Assignment completion or review |
| **Notification** (pokes) | Tell Claude a result is ready | Structured poke in `runtime/dispatch/pokes/orchestrator/` | Process launch or running agent |

## Required flow

```
1. Claude creates assignment with --wake
      → wake record queued for supervisor (notification of work, not launch proof)

2. Persistent supervisor (execution layer)
      → claims when capacity permits (concurrency 1)
      → physically launches assigned agent (Grok primary / Codex fallback)
      → records PID/run state  ← ONLY proof of launch

3. Agent finishes (handoff + complete)
      → outbox written
      → assignment status → awaiting_review   ← completion evidence starts here
      → structured poke to orchestrator only  ← notification evidence only

4. Claude drains poke/outbox
      → reviews branch + handoff
      → records accept | request-changes | reject in Agentic OS

5. If request-changes
      → Claude reactivates/creates correction and uses --wake again
      → supervisor re-launches when capacity permits
```

## Topology (non-negotiable)

- Only **Claude** may assign and `--wake` builders.
- Agents may poke **only** `orchestrator` / Claude.
- Agents must **never** assign, wake, or poke another builder.
- Builder-to-builder reassignment is not autonomous notification.

## Idempotency

- Completing an already `awaiting_review` assignment does not create a new undrained completion poke for the same `(assignment_id, event)`.
- Duplicate completion notifications must not create duplicate reviews or assignments.
- Claude’s resolution verbs (`accept` / `request-changes` / `reject`) remain the only way to open a new correction cycle.

## Operator commands

```bash
# Execution layer (keep running)
python scripts/run_orchestrator.py --agent composer --poll-seconds 5

# Notification layer drain (Claude)
python scripts/assignments.py pokes
python scripts/assignments.py pokes --drain
python scripts/assignments.py outbox
python scripts/assignments.py ingest
python scripts/assignments.py accept|request-changes|reject <id> ...
```

## Anti-confusion rules

1. A successfully written **poke is not a launched process**.
2. A **process launch is not completion** — require outbox, handoff, tests, and terminal/`awaiting_review` state.
3. The passive `scripts/watch_assignments.py` path only claims; it is not the physical launcher.

See also: `docs/PHYSICAL_AGENT_LAUNCHER.md`, ADR-0043 amendments, `docs/GROK_BUILD_LOOP.md`.
