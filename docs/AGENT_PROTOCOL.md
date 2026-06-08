# Agent Protocol v1

This document defines **the contract every agent must follow** to participate
in the Agentic OS. If you are an LLM agent reading this: these rules are
binding for every action you take in this repo.

## 1. Identity
Each agent has a stable lowercase identifier:
`codex`, `claude`, `cursor`, `gemini`, `hermes`, `human`.

Always identify yourself in commits, logs, and handoffs using this exact string.

## 2. Branching
- Work on `agent/<your-id>/<task-id>`.
- Never commit directly to `main`.
- Never merge a PR. Humans merge.

## 3. The Read–Plan–Act–Log–Handoff Loop
Every work session **must** follow this loop:

1. **READ**
   - Pull latest `main`.
   - Read your assigned task: `tasks/active/<id>.yaml`.
   - Read any referenced inputs and the latest handoff (if any).
   - Read recent entries of `logs/agent-events.jsonl` for context.

2. **PLAN**
   - If the task is unclear or risky, **stop** and open an ADR draft in
     `decisions/` with `status: proposed`. Do not act.

3. **ACT**
   - Make changes only inside your branch.
   - Update the task YAML's `status` field as you progress.

4. **LOG**
   - Append at least one event to `logs/agent-events.jsonl` per significant
     action (started, blocked, decision_needed, finished).
   - See §6 for the event schema.

5. **HANDOFF**
   - Before ending your session, write a handoff file (see `HANDOFF_PROTOCOL.md`).
   - Update task `status` to `review`, `blocked`, or `done`.
   - Open a PR with a clear title: `[<agent-id>] <task-id>: <summary>`.

## 4. Task Status Machine
```
todo → in_progress → review → done
                  ↘ blocked ↗
```
Allowed transitions only. Any other transition is invalid. ADR-0005 renames
`todo` to `ready`; during the migration window, `todo` is accepted as a
deprecated alias.

## 5. Risky Actions (Require Human Approval)
An agent **must not** perform any of the following without an approved ADR:
- Deleting files outside `tasks/active/` (archival to `tasks/done/` is fine).
- Modifying `docs/AGENT_PROTOCOL.md`, `docs/ARCHITECTURE.md`, or any schema doc.
- Installing new top-level dependencies or changing build/CI config.
- Running anything that touches the network beyond fetching documented inputs.
- Force-pushing, rebasing shared branches, or rewriting history.
- Editing another agent's in-progress task or handoff.

To request approval: write an ADR with `status: proposed` and `approval: human`,
then log a `decision_needed` event. Wait.

## 6. Event Log Format (`logs/agent-events.jsonl`)
One JSON object per line. Append only. Never edit prior lines.

Canonical vocabulary: `protocol/event_types.py` (ADR-0004 + Phase 2 extension in ADR-0010).

**Required fields:** `ts` (ISO-8601 UTC), `agent`, `type`.

**Phase 1 types (`type` field):** `task_created`, `task_assigned`, `status_changed`,
`handoff_written`, `reviewed`, `decision_recorded`, `blocked`, `note`.

**Phase 2 types (active emitters):** `discovery_completed`, `vault_sync_planned`,
`vault_sync_completed`, `orchestration_planned`, `error`.

**Reserved (not in validator until emitted):** `registry_updated`, `validation_passed`,
`review_packet_created`.

**Optional fields:** `task_id` (or legacy `task`), `detail`, `text`, `ref`.

**Deprecated v1 field:** `event` — historical log lines may still use it; new emitters
must use `type` via `scripts/append_log.py --type <name>`.

Example (current):

```json
{"ts":"2026-06-07T12:00:00Z","agent":"orchestrator","task_id":"T-LANGGRAPH-001","type":"orchestration_planned","detail":"plan generated","ref":"runtime/orchestrator/runs/run-..."}
```

## 6.1 Task Schema v2 Migration Map

ADR-0005 renames the task schema fields below. During the Phase 1.5 to Phase
1.6 migration window, the validator accepts v1 names with warnings. New task
files should use v2 names only.

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

Schema v2 also adds `reviewer`, `created_by`, `phase`, `context`, `goals`,
`non_goals`, and `human_approval_checklist`. `reviewer` is required at
`review` and `done`; `human_approval_checklist` is required when
`requires_human_approval: true`.

## 7. Commit Message Convention
```
[<agent-id>] <task-id>: <imperative summary>

<optional body>

Refs: handoffs/<file>, decisions/ADR-####
```

## 8. When in Doubt
- Stop. Log a `decision_needed` event. Write a draft ADR. Hand off to `claude`
  or `human`. Never guess on architecture, security, or scope.
