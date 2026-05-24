# ADR-0008: Librarian role and shared-memory write rules (PROPOSAL STUB)

- Status: **Draft - Codex to author after ADR-0007 signed**
- Date: 2026-05-24
- Deciders: human (final sign-off), claude (reviewer), codex (author)
- Depends on: ADR-0007
- Related: ADR-0004, ADR-0007, AGENT_PROTOCOL.md

## Context

ADR-0007 accepted a shared memory architecture with three namespaces:
`shared`, `agent/<name>`, and `system/derived`. In the shared memory store,
only the Librarian writes. Every other agent reads freely from shared memory
and writes freely to its own private namespace. This is non-negotiable for
Phase 2 because it is the primary defense against silent memory pollution.

## Decision

Codex must author this section in T-0020. The final ADR must answer:

### 1. Librarian role definition

- What is the Librarian? Agent, process, cron job, persistent service, or
  something else?
- Who runs it? Codex, a dedicated lightweight model, Claude in observer mode,
  or another actor?
- When does it run? On every event, batched, on task completion, or manually?
- How is it audited? Every Librarian write should produce an event in the log
  with references to the source events or files it was derived from.

### 2. Write rules

A Librarian write to shared memory must:

- cite source events from `logs/agent-events.jsonl` or source files with path
  and commit SHA;
- include a confidence score;
- be reversible, with every write producing an undo record;
- pass a deduplication check against existing memory records;
- refuse to write if confidence is below the threshold defined by this ADR.

### 3. What the Librarian extracts

For each memory type in ADR-0007, define the extraction rule. Examples:

- Entity memory: when a new task references a person, file, or ADR not yet in
  the entity store, create the entity record.
- Episodic memory: every event with `type` in `task_created`,
  `status_changed`, `task_assigned`, or `handoff_written` becomes an episodic
  record, unless T-0020 chooses to treat the event log itself as sufficient.
- Semantic memory: extracted conservatively from handoffs and signed ADRs.

### 4. Conflict resolution

When the Librarian's new write contradicts an existing memory record, the
default proposal is: do not overwrite; create a `disputed` annotation and
surface it for human resolution. Codex must confirm or revise this.

### 5. Persona memory write boundary

Personas are owned by the agent they describe. The Librarian does not write
persona memory unless T-0020 explicitly argues for an exception.

### 6. Failure modes

The final ADR must say what happens when:

- the Librarian is down;
- the Librarian writes garbage;
- the Librarian's model changes;
- canonical source files and derived memory disagree.

## Consequences

To be authored in T-0020. The final ADR must enumerate concrete recovery
procedures and the tradeoffs of single-writer shared memory.

## Sign-off

- [ ] human
- [ ] claude (reviewer)
