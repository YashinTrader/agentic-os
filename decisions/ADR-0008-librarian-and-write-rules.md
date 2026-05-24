# ADR-0008: Librarian role and shared-memory write rules

- Status: **Accepted**
- Date: 2026-05-24
- Deciders: human (final sign-off), claude (reviewer), codex (author)
- Depends on: ADR-0007
- Related: ADR-0004, ADR-0007, ADR-0009, AGENT_PROTOCOL.md

## Context

ADR-0007 accepted a local-first memory architecture with three namespaces:

- `shared` - canonical cross-agent memory;
- `agent/<name>` - private writable memory for the owning agent;
- `system/derived` - rebuildable derived records from logs, repo files,
  commits, task YAML, ADRs, and handoffs.

It also established the core safety rule: every agent may read shared memory,
but only the Librarian may write to shared memory. This ADR makes that rule
operational. It does not implement the Librarian and does not define the MCP
adapter contract; ADR-0009 owns the adapter surface.

Memory errors are dangerous because they are quiet. If an incorrect fact lands
in shared memory, future agents may treat it as project truth. Phase 2 must
therefore prefer slow, cited, reversible writes over fast automatic promotion.

## Decision

Use a **batchable local Librarian command** as the only writer to `shared`
memory in Phase 2.

The Librarian is not a new autonomous daemon in Phase 2. It is a dedicated
repo-local role invoked by an agent or human at controlled points:

- after a task reaches `review` or `done`;
- after a PR is merged;
- after an ADR is signed;
- manually when the human requests a memory refresh.

Phase 2.1 may implement the Librarian as a command such as
`scripts/memory_librarian.py` or equivalent, but this ADR approves the role and
rules, not the filename or implementation. A future ADR may promote the
Librarian to a scheduled job or persistent service after the command form has
proven reliable.

### 1. Librarian Role Definition

The Librarian has four responsibilities:

1. Read canonical sources: `logs/agent-events.jsonl`, task YAML, ADRs,
   handoffs, selected repo files, commit metadata, and PR metadata when local.
2. Derive candidate memory records for `system/derived` and possible promoted
   records for `shared`.
3. Validate each candidate against the write rules below.
4. Write accepted records through the memory backend and append audit events.

The Librarian may use a local LLM for summarization and extraction, but the
policy decisions in this ADR do not depend on a model. Deterministic extractors
should be preferred wherever possible:

- task entities from task YAML;
- ADR entities and decision status from ADR front matter/body;
- episodic events from `logs/agent-events.jsonl`;
- repo chunks from file paths, headings, and content hashes.

LLM extraction is allowed only for summaries and semantic facts, and only when
the generated record cites exact sources.

### 2. Run Triggers and Cadence

Phase 2 uses explicit batch runs, not continuous watching:

| Trigger | Required? | Scope |
|---------|-----------|-------|
| Task enters `review` | yes in Phase 2.1 | task YAML, related handoff, new log events |
| Task enters `done` | yes in Phase 2.1 | final task state, merge/PR metadata if available |
| ADR signed | yes in Phase 2.1 | ADR file, index row, related tasks |
| Manual human request | yes | human-specified source refs |
| Every event append | no | deferred; too noisy and too easy to over-extract |
| Scheduled cron | no | deferred until the command path is stable |

Batching is deliberate. It lets agents finish a coherent unit of work before
the Librarian extracts durable facts. Per-event extraction would turn temporary
working notes into long-term memory too early.

### 3. Write Rules

Every Librarian write must satisfy all of these rules.

#### Citation

Each shared-memory record must cite at least one canonical source:

```yaml
source:
  kind: adr | task | event_log | handoff | commit | file
  path: decisions/ADR-0007-memory-architecture.md
  line: 42
  id: ADR-0007
  commit: <sha-or-null>
```

For repo files, use repo-relative path plus commit SHA when available. For
event log entries, use log path plus line number and event ID if present. If a
claim cannot be cited, it cannot enter `shared`.

#### Confidence

Every write carries `confidence` from `0.0` to `1.0`:

- `1.0` - directly copied from a signed ADR, task field, event field, or file
  metadata with deterministic parsing;
- `0.8-0.95` - concise summary of a signed ADR, done task, or accepted handoff
  with exact source refs;
- `0.6-0.79` - model-assisted extraction from non-signed but review-state
  artifacts, with citations;
- below `0.6` - not eligible for `shared`.

The default shared-write threshold is **0.8**. Records below `0.8` may be
written only to `agent/<name>` or held as candidates for human review.

#### Reversibility

Each write must produce an undo record before the write is committed:

```yaml
write_id: memory-write:<stable-id>
operation: create | update | retract | dispute
record_id: memory:<stable-id>
previous_record: null
new_record: {...}
source_refs: [...]
created_at: 2026-05-24T00:00:00Z
created_by: librarian
```

Undo records belong in the memory backend's audit area and must be exportable.
Implementation may also mirror them to JSONL later, but this ADR does not add
a new file format.

#### Deduplication

Before writing, the Librarian must check for duplicate or near-duplicate
records using stable IDs, source refs, entity IDs, and semantic similarity.

If a candidate restates an existing record with the same source and meaning,
the write is skipped. If it adds a new source for the same claim, the existing
record may be updated by appending refs, not by replacing content. If it is a
better summary of the same sources, create an `update` undo record and mark
the previous record `superseded`.

#### Idempotency

The same Librarian run over the same canonical inputs must not create duplicate
shared records. Candidate IDs are derived from source refs and semantic type:

```text
semantic:<sha256(type + normalized_claim + sorted_source_refs)>
episodic:<sha256(event_ref)>
entity:<entity_type>:<canonical_id>
repo_chunk:<path>#<chunk_index>:<content_hash>
summary:<scope>:<sha256(sorted_source_refs)>
```

#### Human-Approval Boundaries

The Librarian must refuse shared writes for:

- uncited claims;
- confidence below `0.8`;
- claims based only on private `agent/<name>` memory;
- claims that contradict accepted ADRs;
- persona records;
- cloud-derived extraction unless the cloud provider was explicitly approved.

These may be emitted as candidate records or `blocked` events for human review,
but not written to `shared`.

### 4. Extraction Rules by Memory Type

| Memory type | Librarian behavior |
|-------------|--------------------|
| Working memory | No extraction. Out of scope per ADR-0007. |
| Short-term memory | Create summaries for completed/review tasks and merged PRs. Source refs must include the task file, handoff, and relevant events. Summaries expire or become superseded when the task is archived. |
| Long-term semantic memory | Extract only from accepted ADRs, done tasks, signed handoffs, and human-approved notes. Prefer exact decision summaries over broad inference. Do not extract from transient comments unless human-approved. |
| Persona memory | Do not write. Persona records are owned by the agent they describe and adapter behavior is deferred to ADR-0009. |
| Episodic memory | Derive from canonical event log entries and selected Git/PR events. The event log remains canonical; episodic memory is an indexed view. |
| Entity memory | Deterministically derive tasks, ADRs, agents, people, files, branches, PRs, and commits from repo files and metadata. Update aliases and relations only with cited evidence. |
| Structured RAG | Chunk selected repo files with path, heading, content hash, and commit SHA. Do not summarize away the source; repo chunks point agents back to canonical files. |

### 5. Conflict Resolution

The Librarian must not silently overwrite contradictions.

When a candidate contradicts an active shared record:

1. keep the existing record active;
2. write a `disputed` annotation that cites both sides;
3. append a `blocked` or `note` event describing the conflict;
4. surface the conflict to the human/dashboard when such a surface exists;
5. wait for human or signed-ADR resolution before retracting or superseding the
   active record.

Accepted ADRs outrank task notes, handoffs, summaries, private memory, and
model output. Newer accepted ADRs may supersede older accepted ADRs only when
they explicitly say so or when a human signs the supersession.

### 6. Audit Events

Every Librarian run must append at least one event to `logs/agent-events.jsonl`
using ADR-0004 vocabulary:

- `note` for run summary, including counts of candidates, writes, skips, and
  conflicts;
- `blocked` when required sources are missing or a conflict needs human review;
- `decision_recorded` only when a new or signed ADR appears, not for every
  memory write.

The event should include `task_id` when a task triggered the run and refs to
the affected source files. The audit log remains append-only; do not rewrite
old events to "fix" memory.

### 7. Failure Modes and Recovery

#### Librarian is down

Reads continue. Agents may keep writing private memory and canonical files.
Shared-memory writes queue as source refs, not as opaque generated records. On
recovery, the Librarian replays from canonical sources and produces idempotent
writes.

#### Librarian writes garbage

Use undo records to retract or supersede the bad writes. Append a `blocked`
event with the affected record IDs and source refs. If more than three bad
writes occur in one run, activate a circuit breaker: stop shared writes and
require human review before the next run.

#### Librarian model changes

Model changes do not mutate existing shared records automatically. Run a dry
run first and compare candidates against current memory. If the new model
changes extraction materially, open an ADR or task note before replacing
records. Because memory is derived, a full rebuild is allowed after human
approval.

#### Canonical sources and memory disagree

Canonical sources win: accepted ADRs, task YAML, handoffs, event log, and Git
history. The Librarian must retract or supersede memory that disagrees with
canonical sources and record the correction with undo/audit entries.

#### Backend unavailable or corrupted

Stop writes, preserve canonical sources, and rebuild memory from repo + log
after backend recovery. No agent should treat backend loss as data loss because
ADR-0007 makes memory a derived view.

#### Duplicate or looping writes

Idempotency keys and dedup checks should prevent repeated writes. If a loop is
detected, stop the run, append a `blocked` event, and require a task/ADR fix
before retrying.

## Consequences

**Positive**

- Shared memory remains conservative, cited, reversible, and rebuildable.
- Batch operation lowers the chance that transient task chatter becomes long
  term truth.
- The extraction rules give Phase 2.1 enough precision to implement a first
  Librarian without inventing policy in code.
- The conflict model gives humans and reviewers a clear place to intervene.

**Negative**

- Shared memory will lag behind the latest event until a Librarian run occurs.
- The single-writer model creates a bottleneck by design.
- Confidence scoring is partly judgment-based for summaries and semantic
  facts; implementation must keep scores explainable.
- Undo records and idempotency add implementation overhead.

**Neutral**

- This ADR does not choose CLI flags, filenames, or a service runner.
- This ADR does not define MCP endpoint schemas; ADR-0009 owns that contract.
- This ADR does not permit direct shared-memory writes by Codex, Claude,
  OpenClaw, Hermes, Antigravity, or any future agent.

## Rejected Alternatives

### Let every agent write shared memory directly

Rejected because it optimizes speed over correctness. A single hallucinated
summary or misunderstood review comment could become shared truth. Private
namespaces already give agents a place to store draft observations; shared
memory needs a promotion gate.

### Make the Librarian a persistent daemon immediately

Rejected for Phase 2. A daemon introduces lifecycle, crash recovery, local
service configuration, and scheduling questions before the extraction policy
has been tested. A batchable command is easier to audit and easier to invoke
from tasks, hooks, or humans.

### Extract semantic memory from every event

Rejected because events are too granular and often describe in-progress work.
Episodic memory can index every event, but semantic memory should come from
settled artifacts: accepted ADRs, done tasks, handoffs, and human-approved
notes.

### Allow low-confidence records into shared memory with warning labels

Rejected. Warning labels are easy for later agents to ignore, and they still
pollute retrieval results. Low-confidence candidates can be held for review or
stored privately; they do not belong in `shared`.

### Let newer records overwrite older records automatically

Rejected because newer does not mean truer. Accepted ADRs may be superseded,
but only explicitly. Otherwise contradictions become disputes until resolved.

## Sign-off

- [x] human - Gabriel Achim approved on 2026-05-24
- [x] claude (reviewer) - Claude Opus 4.7 approved PR #11 on 2026-05-24
