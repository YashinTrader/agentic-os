# Task Schema v2

Tasks are YAML files in `tasks/active/`, `tasks/blocked/`, or `tasks/done/`.
Filename: `<task-id>.yaml`. Task IDs are zero-padded sequential:
`T-0001`, `T-0002`, ...

Schema v2 is defined by `decisions/ADR-0005-task-schema-v2.md`. During the
Phase 1.5 to Phase 1.6 migration window, `scripts/validate.py` accepts v1
field names with warnings. New and migrated task files must use the v2 names.

## Required Fields

```yaml
id: T-0007
title: "Scaffold tasks/ directory and example task"
owner: codex
reviewer: claude
created_by: codex
status: in_progress           # ready | in_progress | review | blocked | done
phase: "1.5"
created_at: 2026-05-22T09:00:00Z
updated_at: 2026-05-22T10:32:11Z

objective: >
  Create the tasks/ directory structure and a worked example task YAML
  so that other agents can copy the pattern.

context: |
  Longer-form rationale, prior art, or motivating events.

goals:
  - Explicit goal 1

non_goals:
  - Explicit out-of-scope item 1

inputs:
  - docs/TASK_SCHEMA.md
  - docs/AGENT_PROTOCOL.md

outputs:
  - tasks/active/T-0007.yaml
  - tasks/active/EXAMPLE.yaml

constraints:
  - Must not modify docs/ files.
  - YAML must validate against this schema.

acceptance:
  - tasks/ directory exists with active/, done/, blocked/ subdirs.
  - At least one example task file is present and parses as YAML.

human_approval_checklist: []

notes: >
  After completion, hand off to claude for schema review.

risk_level: low               # low | medium | high
requires_human_approval: false
priority: high                # high | medium | low
```

## Optional Fields

```yaml
depends_on: [T-0003, T-0005]
blocks: [T-0010]
labels: [phase-1, scaffolding]
estimated_effort: S           # XS | S | M | L | XL
related_decisions: [ADR-0002]
```

## Rename Map From v1

| v1                    | v2                 |
|-----------------------|--------------------|
| `created`             | `created_at`       |
| `updated`             | `updated_at`       |
| `acceptance_criteria` | `acceptance`       |
| `handoff_notes`       | `notes`            |
| `priority: P0`        | `priority: high`   |
| `priority: P1`        | `priority: high`   |
| `priority: P2`        | `priority: medium` |
| `priority: P3`        | `priority: low`    |
| `status: todo`        | `status: ready`    |

## Rules

1. `id` is immutable once assigned.
2. `owner` changes when handed off; old owner is recorded in a handoff file.
3. `reviewer` is required when `status` is `review` or `done` and must differ
   from `owner`.
4. `updated_at` must be refreshed on every write.
5. `status` transitions follow the state machine in `AGENT_PROTOCOL.md`.
6. When `status: done`, the file is moved to `tasks/done/<id>.yaml`.
7. When `status: blocked`, the file is moved to `tasks/blocked/<id>.yaml`
   and a `blocked` event is logged with the blocker reason.
8. If `risk_level: high` or `requires_human_approval: true`, work cannot start
   until a linked ADR has human approval.
9. If `requires_human_approval: true`, `human_approval_checklist` must be a
   non-empty list.
10. A task must not contain both sides of a v1/v2 rename pair.

## Minimum Valid Task

A v2 task is valid if and only if it has: `id`, `title`, `owner`, `status`,
`created_at`, `updated_at`, `objective`, `inputs`, `outputs`, `constraints`,
`acceptance`, `notes`, `risk_level`, `requires_human_approval`, `reviewer`,
`created_by`, `phase`, `goals`, `non_goals`, and `priority`.

During the migration window, v1 tasks remain accepted with warnings if they do
not mix v1 and v2 names in the same rename pair.
