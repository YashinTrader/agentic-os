# Audit Event Schema

Agentic OS records append-only audit events in `logs/agent-events.jsonl`. Each
line is one JSON object. Events are designed for low-tech review, dashboard
rendering, and deterministic agent handoffs.

## Base Event

Every event uses these fields:

| field | type | required | description |
|-------|------|----------|-------------|
| `ts` | string | yes | UTC ISO-8601 timestamp, for example `2026-05-25T19:48:00Z`. |
| `agent` | string | yes | Actor that emitted the event, such as `codex`, `claude`, `hermes`, or `librarian`. |
| `type` | string | yes | One of the ADR-0004 event types. |
| `task_id` | string | context-dependent | Task identifier when the event is task-scoped. |
| `detail` | string | optional | Human-readable summary. |
| `ref` | string | optional | Repo-relative file or command reference. |

ADR-0004 is the source of truth for the closed event vocabulary. The currently
allowed values are:

- `task_created`
- `task_assigned`
- `status_changed`
- `handoff_written`
- `reviewed`
- `decision_recorded`
- `blocked`
- `note`

Older log entries may still use legacy v1 fields such as `event`; the validator
warns for those during the migration window.

## Task Events

Task lifecycle events should include enough structure for a dashboard to group
and filter by task without parsing prose.

```json
{"ts":"2026-05-25T19:40:00Z","agent":"codex","type":"task_created","task_id":"T-0027","detail":"created T-0027 Librarian fixture coverage follow-up from AIA-11","ref":"tasks/active/T-0027.yaml"}
```

```json
{"ts":"2026-05-25T19:48:00Z","agent":"codex","type":"status_changed","task_id":"T-0027","detail":"moved T-0027 to done after fixture coverage expansion and Codex lead approval","ref":"tasks/done/T-0027.yaml"}
```

When available, emitters should include explicit `from` and `to` fields for
`status_changed` events. Existing events that only carry `detail` are still
accepted during the Phase 1.x migration window.

## Librarian Run Summary Events

The Phase 2.1 Librarian emits a dry-run summary as a `note` event. It must not
write to Cognee or any shared-memory backend during Phase 2.1.

Required Librarian fields:

| field | type | required | description |
|-------|------|----------|-------------|
| `type` | string | yes | Always `note` for Phase 2.1 Librarian summaries. |
| `agent` | string | yes | Always `librarian`. |
| `detail` | string | yes | Summary label, currently `Librarian dry-run summary`. |
| `counts` | object | yes | Structured run counters. |
| `counts.candidates` | number | yes | Total candidate records evaluated. |
| `counts.writes` | number | yes | Candidates that passed policy and would write, or are write-planned when the gate changes. |
| `counts.skips` | number | yes | Candidates skipped by policy, duplicate detection, or circuit breaker. |
| `counts.conflicts` | number | yes | Candidates rejected as conflicting with an earlier record. |
| `circuit_breaker` | boolean | yes | Whether the run opened the bad-candidate circuit breaker. |
| `shared_writes_enabled` | boolean | yes | Whether shared writes were requested. This remains `false` by default. |
| `ref` | string | yes | `scripts/memory_librarian.py`. |

Example:

```json
{"ts":"2026-05-25T20:00:00Z","agent":"librarian","type":"note","task_id":"T-0028","detail":"Librarian dry-run summary","counts":{"candidates":12,"writes":7,"skips":4,"conflicts":1},"circuit_breaker":false,"shared_writes_enabled":false,"ref":"scripts/memory_librarian.py"}
```

## Phase 2.1 Constraints

Audit events may describe candidate decisions and dry-run summaries, but they
must not imply that shared-memory writes happened unless the backend gate has
intentionally changed.

For Phase 2.1:

- no daemon or watcher emits events
- no LLM extraction emits events
- no cloud write emits events
- no MCP write tool emits events
- `shared_writes_enabled` defaults to `false`
- `--apply` work must remain a no-op until the backend gate changes

## Validation

Run:

```bash
python3 scripts/validate.py
python3 -m unittest
```

`scripts/validate.py` checks event vocabulary and warns on legacy v1 event
fields. It does not rewrite existing audit history.
