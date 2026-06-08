# ADR-0004: Event vocabulary standardization for logs/agent-events.jsonl

- Status: accepted
- Date: 2026-05-23
- Deciders: human (final), claude (architect), codex (implementer)
- Supersedes: none
- Related: ADR-0001 (file-based protocol), ADR-0003 (Phase 1 protocol corrections)

## Context

Across Phase 1 we accumulated a JSONL event log at `logs/agent-events.jsonl`
without ever fixing the set of allowed event `type` values. Reviewing T-0008,
T-0011, and T-0012, the following organically-coined types appear in the wild:

- `task_created`
- `task_picked` / `picked_up`
- `status_changed`
- `task_in_progress`
- `handoff_created` / `handoff_written`
- `reviewed`
- `task_completed` / `task_done`
- `note`
- `decision_recorded`

This is vocabulary drift. Two events that mean the same thing have different
names depending on which agent emitted them. Any future read surface (a
dashboard, a summarizer agent, a metrics view) would have to normalize this
post-hoc, which defeats the point of a structured log.

The log is small, append-only, and easy to migrate. We should fix the
vocabulary now, before Phase 1.6 (dashboard) consumes it.

## Decision

Adopt a closed set of 8 event types for Phase 1.x. Any emitter that wants a
new type must add it via a new ADR (cheap: one bullet under "Additions").

### Allowed `type` values

| type              | when                                                       | required fields beyond base                 |
|-------------------|------------------------------------------------------------|---------------------------------------------|
| `task_created`    | a new task YAML is written to `tasks/active/`              | `task_id`, `created_by`                     |
| `task_assigned`   | `owner` field of a task changes (incl. first assignment)   | `task_id`, `owner`                          |
| `status_changed`  | any change to a task's `status` field                      | `task_id`, `from`, `to`                     |
| `handoff_written` | a file is created under `handoffs/`                        | `task_id`, `from_agent`, `to_agent`, `path` |
| `reviewed`        | a reviewer records a verdict on a task in `review` state   | `task_id`, `reviewer`, `verdict`            |
| `decision_recorded` | a new or signed ADR appears under `decisions/`           | `adr_id`, `status`                          |
| `blocked`         | an agent cannot proceed and needs human/other-agent input  | `task_id`, `reason`                         |
| `note`            | free-form context that does not fit the above              | `task_id` (optional), `text`                |

### Base fields (required on every event)

```json
{
  "ts": "ISO-8601 UTC, e.g. 2026-05-23T12:34:56Z",
  "agent": "codex | claude | cursor | hermes | human | ...",
  "type": "<one of the 8 above>"
}
```

### Explicitly removed / renamed

- `task_picked`, `picked_up`, `task_in_progress` → emit `status_changed` with `from`/`to`.
- `task_completed`, `task_done` → emit `status_changed` with `to: done`.
- `handoff_created` → renamed to `handoff_written`.

### Validator behavior

`scripts/validate.py` SHOULD (not MUST, in this ADR) warn — not error — on
unknown `type` values for one phase, then error in the ADR that closes Phase
1.6. This gives us a migration window without breaking the current log.

## Consequences

**Positive**
- Any future read surface (dashboard, summarizer, audit) can rely on a closed vocabulary.
- New event types are cheap to add but require an ADR, which preserves the audit trail.
- Backward-compatible during the warning phase.

**Negative**
- Existing log entries with deprecated types remain in history. We do not rewrite history; the warning phase carries them.
- Slight friction for agents: they must look up the table instead of inventing a verb.

**Neutral**
- Does not change file-based architecture, dependencies, or directory layout.

## Migration plan

1. Land this ADR as `status: accepted` after human sign-off.
2. Open a task (T-0014 candidate) to:
   - Add the allowed-types table to `docs/AGENT_PROTOCOL.md`.
   - Add a `--warn-unknown-event-types` check to `scripts/validate.py`.
   - Update `scripts/log_event.py` to validate `--type` against the table (warn, do not block).
3. After Phase 1.6 dashboard lands, flip the validator from warn to error in a follow-up ADR.

## Phase 2 extension (ADR-0010, 2026-06-07)

Additional closed `type` values for Phase 2 operational events:

| type | when |
|------|------|
| `discovery_completed` | daemon CLI discovery finished successfully |
| `vault_sync_planned` | Obsidian dry-run planned notes |
| `vault_sync_completed` | Obsidian one-way sync finished |
| `orchestration_planned` | LangGraph finalize wrote plan (no execution) |
| `error` | operational failure (daemon, sync, etc.) |

Reserved (documented, not validated until an emitter exists):
`registry_updated`, `validation_passed`, `review_packet_created`.

Implemented in `protocol/event_types.py`. Validator errors on unknown `type` values.

## Open questions

- Do we need a `phase` field on every event? (Probably yes, but defer to the implementation task.)
- Should `note` be allowed without a `task_id`? (Tentatively yes — system-level notes are useful.)

## Sign-off

- [x] human - Gabriel Achim approved following Claude direction on 2026-05-23
- [x] claude (proposer)
- [x] codex (implementer, on acceptance)
