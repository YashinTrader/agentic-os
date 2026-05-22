# Architectural Decisions

This repo uses lightweight **ADRs (Architecture Decision Records)** for any
non-trivial decision. ADRs live in `decisions/ADR-####-<slug>.md`.

The canonical index is `decisions/INDEX.md`.

## When to Write an ADR
Write an ADR when:
- The decision affects more than one agent or task.
- The decision changes a schema, protocol, or directory layout.
- The decision involves a risky action (see `AGENT_PROTOCOL.md` §5).
- The decision was non-obvious and a future reader would ask "why?"

Do **not** write an ADR for routine implementation choices (variable names,
trivial refactors).

## ADR Template
```markdown
# ADR-0003: Handoff File Naming Convention

**Status:** proposed | accepted | rejected | superseded-by-ADR-####
**Date:** 2026-05-22
**Author (agent):** codex
**Reviewer (agent):** claude
**Approval:** none | human   # 'human' required for risky decisions

## Context
We need a deterministic, conflict-free naming scheme for handoff files so
multiple handoffs on the same task don't collide.

## Decision
Use `<task-id>__<from>__to__<to>.md`. If a second handoff occurs between the
same pair, append `__<ISO-timestamp>`.

## Alternatives Considered
1. Sequential numbering (`T-0007__handoff-2.md`) — rejected: requires reading
   directory state, race-prone.
2. UUID suffix — rejected: not human-readable.

## Consequences
- Pro: human-readable, sortable, no central counter.
- Con: timestamp collisions theoretically possible at sub-second granularity.

## References
- handoffs/T-0007__codex__to__claude.md (first use)
- logs/agent-events.jsonl
```

## Workflow
1. Author agent writes ADR with `status: proposed`.
2. Logs a `decision_needed` event referencing the ADR path.
3. Reviewer (usually `claude`) edits the ADR, sets `status: accepted` or `rejected`.
4. If `approval: human` is required, a human must add their sign-off line at
   the bottom: `Approved-by: <name> on <date>`.
5. Accepted ADRs are appended to `decisions/INDEX.md`.

## Index Format (`decisions/INDEX.md`)
```
| ID       | Title                              | Status   | Date       |
|----------|------------------------------------|----------|------------|
| ADR-0001 | Use Git repo as message bus        | accepted | 2026-05-22 |
| ADR-0002 | YAML for task files                | accepted | 2026-05-22 |
| ADR-0003 | Handoff file naming convention     | proposed | 2026-05-22 |
```

## Rule
**No silent decisions.** If an agent makes a choice that would surprise a
future reader, it must produce an ADR — even a short one.
