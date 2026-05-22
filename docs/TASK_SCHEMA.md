# Task Schema v1

Tasks are YAML files in `tasks/active/`. Filename: `<task-id>.yaml`.
Task IDs are zero-padded sequential: `T-0001`, `T-0002`, …

## Required Fields
```yaml
id: T-0007
title: "Scaffold tasks/ directory and example task"
owner: codex                  # current agent responsible
status: in_progress           # todo | in_progress | review | blocked | done
created: 2026-05-22T09:00:00Z
updated: 2026-05-22T10:32:11Z

objective: >
  Create the tasks/ directory structure and a worked example task YAML
  so that other agents can copy the pattern.

inputs:
  - docs/TASK_SCHEMA.md
  - docs/AGENT_PROTOCOL.md

outputs:
  - tasks/active/T-0007.yaml
  - tasks/active/EXAMPLE.yaml

constraints:
  - Must not modify docs/ files.
  - YAML must validate against this schema.
  - No external dependencies.

acceptance_criteria:
  - tasks/ directory exists with active/, done/, blocked/ subdirs.
  - At least one example task file is present and parses as YAML.
  - PHASE_1_TASKS.md updated with the new task entry.

handoff_notes: >
  After completion, hand off to claude for schema review.
  Flag any ambiguities found in the schema doc.

risk_level: low               # low | medium | high
requires_human_approval: false
```

## Optional Fields
```yaml
priority: P1                  # P0 (urgent) … P3 (nice-to-have)
depends_on: [T-0003, T-0005]
blocks: [T-0010]
labels: [scaffolding, phase-1]
estimated_effort: S           # XS | S | M | L | XL
related_decisions: [ADR-0002]
```

## Rules
1. **`id` is immutable** once assigned.
2. **`owner` changes** when handed off; old owner recorded in handoff file.
3. **`updated`** must be refreshed on every write.
4. **`status`** transitions must follow the state machine in `AGENT_PROTOCOL.md` §4.
5. When `status: done`, the file is moved to `tasks/done/<id>.yaml`.
6. When `status: blocked`, the file is moved to `tasks/blocked/<id>.yaml`
   and a `blocked` event is logged with the blocker reason.
7. If `risk_level: high` or `requires_human_approval: true`, work cannot start
   until a linked ADR has `approval: human`.

## Minimum Valid Task
A task is valid if and only if it has: `id`, `title`, `owner`, `status`,
`created`, `updated`, `objective`, `inputs`, `outputs`, `constraints`,
`acceptance_criteria`, `handoff_notes`, `risk_level`, `requires_human_approval`.
