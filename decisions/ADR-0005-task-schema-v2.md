# ADR-0005: Task schema v2 — field renames, additions, and migration

- Status: accepted
- Date: 2026-05-23
- Deciders: human (final), claude (architect), codex (implementer)
- Supersedes: none (extends the schema defined in `docs/TASK_SCHEMA.md`)
- Related: ADR-0001, ADR-0003, ADR-0004

## Context

During T-0011, T-0012, and the dashboard V0 review, the architect (Claude)
began referring to task fields by names that did not match the live schema
in `docs/TASK_SCHEMA.md`:

| Architect was using   | Live schema (`docs/TASK_SCHEMA.md` at main)  |
|-----------------------|----------------------------------------------|
| `created_at`          | `created`                                    |
| `updated_at`          | `updated`                                    |
| `acceptance`          | `acceptance_criteria`                        |
| `notes`               | `handoff_notes`                              |
| `priority: high|medium|low` | `priority: P0..P3`                     |

Additionally, the architect introduced fields that were never added to the
schema doc but were used in real task YAML in the repo:

- `phase` — which Phase (1 / 1.5 / 1.6 / 2) a task belongs to
- `reviewer` — distinct from `owner`, enforces reviewer ≠ owner
- `created_by` — provenance of the task file
- `context` — long-form rationale beyond `objective`
- `goals` — list of explicit goals (complements `objective`)
- `non_goals` — list of explicit scope exclusions
- `human_approval_checklist` — items the human signs off on at review time

Codex caught this drift in the PR #1 inspection. The current state is
ambiguous: T-0013 carries both old and new fields. Two paths exist:

- Path A: Roll back all drift, keep v1 schema as-is.
- Path B: Formalize the additions/renames as schema v2 and migrate.

We choose Path B. The new fields are not cosmetic — they encode lessons
from ADR-0003 (`non_goals`, `human_approval_checklist`, `reviewer`),
support ADR-0004 phase tracking (`phase`), and improve auditability
(`created_by`). Rolling them back would be lossy.

## Decision

### v2 schema (required fields)

```yaml
id: T-0007
title: "..."
owner: codex                     # current agent responsible
reviewer: claude                 # must differ from owner; required at status >= review
created_by: claude               # agent or human that authored the task file
status: ready                    # ready | in_progress | review | blocked | done
phase: "1"                       # "1" | "1.5" | "1.6" | "2" | ...
created_at: 2026-05-22T09:00:00Z # ISO-8601 UTC
updated_at: 2026-05-22T10:32:11Z # ISO-8601 UTC, refreshed on every write
objective: >
  Short, one-paragraph statement of what the task accomplishes.
context: |
  Optional longer-form rationale, prior art, motivating events.
goals:
  - Explicit goal 1
  - Explicit goal 2
non_goals:
  - Explicit out-of-scope item 1
  - Explicit out-of-scope item 2
inputs:
  - path/to/file.md
outputs:
  - path/to/produced-file.yaml
constraints:
  - Constraint 1
acceptance:
  - Acceptance criterion 1
  - Acceptance criterion 2
human_approval_checklist:
  - Item the human must sign off on at review
notes: >
  Free-form notes for the next agent or the human.
risk_level: low                  # low | medium | high
requires_human_approval: false
priority: high                   # high | medium | low
```

### v2 schema (optional fields)

```yaml
depends_on: [T-0003, T-0005]
blocks: [T-0010]
labels: [phase-1, scaffolding]
estimated_effort: S              # XS | S | M | L | XL
related_decisions: [ADR-0001, ADR-0003]
```

### Renames (v1 → v2)

| v1                    | v2                  |
|-----------------------|---------------------|
| `created`             | `created_at`        |
| `updated`             | `updated_at`        |
| `acceptance_criteria` | `acceptance`        |
| `handoff_notes`       | `notes`             |
| `priority: P0`        | `priority: high`    |
| `priority: P1`        | `priority: high`    |
| `priority: P2`        | `priority: medium`  |
| `priority: P3`        | `priority: low`     |

Note: P0/P1 both map to `high`. This collapses a distinction that was never
actually used; if urgency needs to be re-expressed later, add a `severity`
field via a future ADR.

### Additions

- `reviewer` (required at `status` ∈ {review, done})
- `created_by` (required)
- `phase` (required)
- `context` (optional)
- `goals` (required, can be empty list)
- `non_goals` (required, can be empty list)
- `human_approval_checklist` (required when `requires_human_approval: true`, otherwise optional)

### Removals

- `acceptance_criteria` → renamed (not removed in the migration window; see below)
- `handoff_notes` → renamed (same)

### Status vocabulary

`status` adds `ready` (was implicit via `todo`). The canonical set is:

`ready | in_progress | review | blocked | done`

`todo` is accepted as an alias for `ready` for one phase, then dropped.

### Validator behavior (migration window)

`scripts/validate.py`:

- **Accepts** both v1 and v2 field names for one full phase (Phase 1.5 → end of Phase 1.6).
- **Warns** (not errors) when v1 names are used after this ADR is `accepted`.
- **Errors** on v1 names starting with a follow-up ADR after Phase 1.6 closes.
- **Errors immediately** if both `created` and `created_at` (or any other rename pair) are present on the same task — pick one.
- **Errors immediately** if `status` is `review` or `done` without a `reviewer`.
- **Errors immediately** if `requires_human_approval: true` without a non-empty `human_approval_checklist`.

### Migration

A single task, `T-0015`, executes the one-shot migration:

1. Update `docs/TASK_SCHEMA.md` to v2.
2. Update `scripts/validate.py` to enforce v2 rules with the warn-then-error behavior above.
3. Walk `tasks/active/`, `tasks/done/`, `tasks/blocked/`; rewrite every file to v2 field names.
4. Append the rename map to `docs/AGENT_PROTOCOL.md`.
5. Append a `decision_recorded` event to `logs/agent-events.jsonl`.

## Consequences

**Positive**
- Schema matches what agents are actually writing and what reviewers need.
- `reviewer`, `non_goals`, `human_approval_checklist` make ADR-0003's lessons mechanically enforceable.
- `phase` makes ADR-0004's event log sortable by phase without parsing IDs.
- Migration is one task, one phase window — bounded.

**Negative**
- Existing tasks need a one-shot rewrite. Mitigated by `T-0015` doing it programmatically.
- The validator carries v1 acceptance for one phase. Small code overhead.

**Neutral**
- No new dependencies. No new directories. File-based architecture unchanged.

## Sign-off

- [x] human - Gabriel Achim approved following Claude direction on 2026-05-23
- [x] claude (proposer)
- [x] codex (implementer, on acceptance)
