# ADR-0006: Dashboard is read-write (ratification)

- Status: accepted
- Date: 2026-05-24
- Deciders: human (final sign-off), claude (reviewer), antigravity (implementer of record)
- Supersedes: partial relaxation of T-0013 non_goals
- Related: ADR-0004 (event vocabulary), AGENT_PROTOCOL.md, scripts/update_task.py, scripts/create_task.py, scripts/add_comment.py

## Context

T-0013 ("v2 Kanban dashboard") was originally seeded with `non_goals` that
included "writing back to repo" and an acceptance criterion of "zero writes to
repo files". During implementation the human verbally expanded scope to allow
the dashboard to:

1. Append `note` events to `logs/agent-events.jsonl` (comments).
2. Create new task YAMLs in `tasks/active/`.
3. Move task YAMLs between `tasks/active/`, `tasks/done/`, `tasks/blocked/`
   and append `status_changed` / `task_assigned` events.

The verbal scope change was implemented in PR #6 and merged, but the task YAML
was never amended and no ADR was written. This ADR ratifies the scope change
retroactively and codifies the safety properties the read-write dashboard must
preserve going forward.

## Decision

The dashboard is **read-write** against the repo. It is a first-class UI over
the file-based coordination protocol, not a passive viewer.

To keep the protocol invariants intact, the dashboard MUST satisfy:

1. **Single source of truth for guardrails.** The dashboard MUST NOT
   reimplement guardrail logic. It MUST either:
   - (a) shell out to `scripts/update_task.py`, `scripts/create_task.py`,
     `scripts/add_comment.py`, OR
   - (b) import and call the same enforcement functions those scripts use.

   Option (a) is preferred for Phase 1.7. Option (b) requires the enforcement
   logic to be extracted into a shared module (`scripts/_guardrails.py`) that
   both CLI and dashboard import.

2. **Guardrails preserved.** Every write path from the dashboard MUST enforce:
   - `owner != reviewer` on create and on reassignment.
   - Risky-path auto-escalation: any task whose `outputs` touch
     `scripts/`, `decisions/`, `docs/AGENT_PROTOCOL.md`, `docs/TASK_SCHEMA.md`,
     `docs/HANDOFF_PROTOCOL.md`, or `.github/` MUST be created with
     `requires_human_approval: true` and a non-empty `human_approval_checklist`.
   - Event vocabulary restricted to ADR-0004's 8-type closed set.
   - `updated_at` refreshed on every write.

3. **Auditability.** Every dashboard-originated write MUST append an event to
   `logs/agent-events.jsonl` with `actor` set to the authenticated user (for
   now: `human` — multi-user auth is out of scope for Phase 1.7).

4. **No silent schema drift.** Dashboard-created task YAMLs MUST conform to
   TASK_SCHEMA.md v2. The dashboard MUST reject creates that would produce a
   non-conforming file.

5. **Read-only by default for memory.** This ADR applies only to repo files.
   The dashboard remains read-only against the future memory store (Phase 2)
   until a separate ADR opens that surface.

## Consequences

**Positive**
- Human-in-the-loop convenience without leaving the dashboard.
- The dashboard becomes the canonical UI for non-agent participants.
- T-0013's verbal scope change is now on the record.

**Negative**
- The dashboard now has the same blast radius as the CLI. Bugs in the
  dashboard can corrupt task state.
- Guardrail logic must be extracted into a shared module OR the dashboard must
  shell out, adding a coupling that did not exist in PR #6.

**Mitigations**
- T-0017 (this pack) hardens the dashboard ↔ CLI parity and is gating for
  closing this ADR.
- Pre-merge checklist for any future dashboard PR MUST include
  "diff against `non_goals` line by line".

## Procedural lesson

Verbal scope changes are not scope changes. The task YAML is the contract. If
the contract changes, the YAML changes first, in a `chore:` PR, before the
implementation PR. This rule is now added to AGENT_PROTOCOL.md (T-0018,
periphery cleanup).

## Sign-off

- [x] human
- [x] claude (reviewer)
