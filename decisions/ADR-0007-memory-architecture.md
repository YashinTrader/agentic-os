# ADR-0007: Memory architecture for Agentic OS

- Status: **Proposed**
- Date: 2026-05-24
- Deciders: human (final sign-off), claude (reviewer), codex (author)
- Related: ADR-0001 (Git repo as message bus), ADR-0004 (event vocabulary),
  ADR-0005 (task schema v2), ADR-0008 (Librarian and write rules, pending),
  ADR-0009 (MCP adapter contract, pending)

## Context

Phase 1 gave Agentic OS a local-first, file-based coordination plane:
task YAML, handoffs, ADRs, and `logs/agent-events.jsonl`. That is enough for
auditable work, but not enough for agents to remember durable facts across
sessions, answer relationship-heavy questions, or retrieve project context
without rereading the whole repository.

Phase 2 introduces memory, but no memory implementation may land until
ADR-0007, ADR-0008, and ADR-0009 are signed. This ADR decides the storage
architecture and memory scope only. It does not decide Librarian write policy
or the MCP tool contract.

The kickoff prompt refers to an "agent-memory article in repo root"; that
article is not present on `origin/main` at the time this ADR is authored.
This ADR therefore uses the memory taxonomy from the T-0019 stub itself:
working memory, short-term memory, long-term semantic memory, persona memory,
episodic memory, entity memory, and structured RAG over the repo.

### Memory types in scope for Phase 2

| Memory type | Phase 2 scope | Rationale |
|-------------|---------------|-----------|
| Working memory | Deferred | Lives inside each agent process/context window. Agentic OS should not manage transient token-window state yet. |
| Short-term memory | In scope as derived summaries | Store compact summaries of recent task threads, handoffs, and review state so agents can resume without replaying every file. |
| Long-term semantic memory | In scope | Store durable project facts, architectural constraints, accepted decisions, and recurring preferences. |
| Persona memory | Minimal Phase 2 scope | Store agent identity metadata and capability descriptors as records, but defer behavior-shaping/persona injection details to ADR-0009. |
| Episodic memory | In scope as a derived view | Preserve "what happened, when, and who did it" by deriving records from `logs/agent-events.jsonl`, handoffs, commits, and ADR status changes. |
| Entity memory | In scope | Maintain canonical records for tasks, ADRs, agents, files, branches, PRs, and people. |
| Structured RAG over repo | In scope | Index README, docs, ADRs, task YAML, handoffs, scripts, and selected code so agents can retrieve source-grounded context. |

### Requirements

- Local-first by default: no external API calls for storage, embedding, graph
  operations, enrichment, or retrieval unless explicitly enabled.
- Rebuildable: memory must be derivable from canonical files and Git history.
- Namespaced: every agent can have private writable memory, while shared
  memory writes are gated by the Librarian policy in ADR-0008.
- MCP-ready: the memory store must be usable behind a narrow read API in
  ADR-0009 without binding the repository to one agent vendor.
- Auditable: every memory record must keep provenance back to tasks, ADRs,
  log events, commits, files, or handoffs.

## Decision

Use **Cognee** as the primary Phase 2 memory backend, configured in a
local-first profile:

- graph store: local Kuzu for single-user development, with Neo4j as the
  documented multi-agent/concurrent upgrade path;
- vector store: local LanceDB by default;
- relational metadata store: local SQLite by default;
- LLM and embedding providers: local Ollama plus local embeddings
  (Ollama embeddings or Fastembed) by default.

Cognee is selected because Agentic OS needs both semantic retrieval and
relationship traversal. A pure vector memory can retrieve similar text, but it
is weaker at questions like "which ADR approved the schema that changed this
task field?" or "what handoff and event sequence led to this blocked task?"
Cognee gives us a graph-plus-vector architecture while already exposing an
MCP-oriented deployment path.

### Backend comparison

| Backend | Graph support | Vector support | MCP support | Local-first viability | License | Operational complexity | Escape hatch |
|---------|---------------|----------------|-------------|-----------------------|---------|------------------------|--------------|
| Cognee | Yes. Supports Kuzu locally and Neo4j/Neptune/Memgraph production paths. | Yes. LanceDB local default, plus PGVector/Chroma/Qdrant/Redis/Falkor options. | Native Cognee MCP server with stdio, HTTP, and SSE transports. | Strong if both LLM and embeddings are configured locally; docs warn to configure both to avoid OpenAI fallback. | Apache-2.0. | Medium. More moving parts than a vector-only store, but aligned with graph needs. | Export/rebuild from canonical files; swap Kuzu/LanceDB for Neo4j/PGVector later. |
| Mem0 | Current OSS v3 removed graph store support and replaced it with entity linking in the vector store. | Yes. Local Qdrant default and configurable vector providers. | MCP exists, but platform MCP is cloud-first; OSS integration would still need adapter decisions. | Viable with local providers, but defaults use OpenAI LLM/embeddings unless overridden. | Apache-2.0. | Low to medium. Easier than Cognee, but less graph-native. | Good fallback if graph requirements are relaxed. |
| Letta | Agent-state model with memory blocks and archival memory, not a general shared project knowledge graph. | Yes for archival memory search when embeddings are configured. | Can connect agents to MCP servers; not primarily an MCP memory backend for other agents. | Self-hostable, but Docker/server model is heavier and agent-centric. | Apache-2.0. | High for this use case because it wants to own agent runtime state. | Useful later for stateful agent experiments, not Phase 2 shared memory. |
| Roll-your-own SQLite + FAISS/sqlite-vec + graph layer | Whatever we build. | Yes if we add an embedded vector extension. | Only if we build it. | Excellent control, but every behavior is ours to design and maintain. | Ours. | High hidden complexity: ingestion, graph extraction, ranking, migration, observability. | Maximum escape hatch but highest design burden. |

### Local-first guarantee

The Phase 2 default profile must run fully on the local machine:

```text
LLM_PROVIDER=ollama
LLM_MODEL=<local model>
LLM_ENDPOINT=http://localhost:11434/v1
LLM_API_KEY=ollama

EMBEDDING_PROVIDER=fastembed
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIMENSIONS=384

GRAPH_DATABASE_PROVIDER=kuzu
VECTOR_DB_PROVIDER=lancedb
RELATIONAL_DATABASE=sqlite:///memory/cognee/cognee.db
```

The exact model names are implementation details for Phase 2.1. The important
rule is architectural: implementation must configure both the LLM provider and
embedding provider to local backends together. A partial configuration that
sets only one of them is not acceptable because it can silently fall back to a
cloud provider.

Optional cloud or managed backends may exist only behind explicit flags and
must be off by default. Examples: OpenAI/Anthropic/Gemini LLM providers, Neo4j
Aura, Neptune, managed Postgres, or Cognee Cloud. Enabling any of them requires
a task note, configuration diff, and human approval because it changes the
data boundary.

### Shared vs. private memory

Adopt the default from the T-0019 stub:

- every agent may read shared memory;
- every agent gets a private namespace it can write to freely;
- shared memory is write-restricted and must go through the Librarian policy
  defined in ADR-0008;
- all records, including private records, carry `created_by`, `namespace`,
  source refs, and confidence.

Namespaces:

| Namespace | Writer | Readers | Purpose |
|-----------|--------|---------|---------|
| `shared` | Librarian only | all agents | Canonical project memory and cross-agent facts. |
| `agent/<name>` | owning agent | owning agent by default; shared read only via explicit ADR-0009 tool/permission | Draft observations, preferences, scratch summaries, agent-local heuristics. |
| `system/derived` | ingestion jobs | all agents | Rebuildable derived records from logs, repo files, commits, and task YAML. |

The shared store is intentionally conservative. Memory writes are quiet,
sticky, and hard to audit after the fact; unrestricted shared writes would
turn hallucinations into infrastructure. Private memory lets agents learn
without contaminating shared state. The Librarian gives Phase 2 one controlled
path for promotion from private/derived observations into shared memory.

### Migration path from `logs/agent-events.jsonl`

`logs/agent-events.jsonl` remains canonical. The memory store is a derived
view that can always be rebuilt from:

- `logs/agent-events.jsonl`;
- task YAML in `tasks/active`, `tasks/blocked`, and `tasks/done`;
- ADR files in `decisions/`;
- handoff files in `handoffs/`;
- Git commit metadata and PR metadata when locally available;
- selected repository docs and scripts.

Phase 2.1 should import existing event log entries into episodic memory on
first run, but the import must be idempotent. The importer should derive stable
IDs from source refs, for example:

```text
event:<sha256(log_path + line_number + ts + type)>
task:<task_id>
adr:<adr_id>
file:<repo_relative_path>
handoff:<repo_relative_path>
```

The event log does not become a cache of the memory store. It remains the
append-only audit trail. If the memory database is deleted, agents should be
able to rebuild it from the repo plus the log. If the log and memory disagree,
the log and repo files win.

## Memory Record Schema

All memory records share a common envelope:

```yaml
id: memory:<stable-id>
type: semantic_fact | short_term_summary | persona | episodic_event | entity | repo_chunk
namespace: shared | agent/<name> | system/derived
content: "Human-readable memory text."
source:
  kind: task | adr | event_log | handoff | commit | file | agent_note
  path: tasks/active/T-0019.yaml
  line: 12
  id: T-0019
created_at: 2026-05-24T00:00:00Z
created_by: codex
confidence: 0.0
refs:
  tasks: []
  adrs: []
  events: []
  files: []
  commits: []
  handoffs: []
visibility: shared | private
status: active | superseded | retracted
ttl: null
metadata: {}
```

### Type-specific fields

#### `short_term_summary`

```yaml
summary_scope: task | branch | conversation | review
window_start: 2026-05-24T00:00:00Z
window_end: 2026-05-24T01:00:00Z
covered_refs:
  events: []
  handoffs: []
  commits: []
open_questions: []
next_actions: []
```

#### `semantic_fact`

```yaml
fact_kind: architecture | constraint | preference | project_state | decision_summary
subject: "Agentic OS memory"
predicate: "uses"
object: "Cognee as proposed backend"
evidence_refs:
  adrs: ["ADR-0007"]
valid_from: 2026-05-24T00:00:00Z
valid_until: null
```

#### `persona`

```yaml
agent: codex
capabilities: []
style_notes: []
tooling_notes: []
approval_boundaries: []
source_of_truth: docs/AGENT_PROTOCOL.md
```

Persona records describe agent capabilities and operating constraints; they
must not silently rewrite an agent's system prompt. Prompt injection and agent
configuration mechanics belong in ADR-0009.

#### `episodic_event`

```yaml
event_type: status_changed
actor: codex
occurred_at: 2026-05-24T00:00:00Z
event_ref: logs/agent-events.jsonl:42
task_id: T-0019
sequence: 42
```

#### `entity`

```yaml
entity_type: task | adr | agent | person | file | branch | pr
canonical_id: T-0019
name: "Author ADR-0007"
aliases: []
properties: {}
relations:
  - predicate: depends_on
    target: ADR-0004
```

#### `repo_chunk`

```yaml
path: docs/AGENT_PROTOCOL.md
chunk_id: docs/AGENT_PROTOCOL.md#0001
content_hash: sha256:<hash>
language: markdown
symbols: []
heading_path: ["Agent Protocol", "Logging"]
```

Repo chunks are for structured RAG. They must preserve enough path and heading
metadata for an agent to reopen the source file instead of trusting the memory
record blindly.

## Consequences

**Positive**

- The selected backend matches Agentic OS's real retrieval problem: semantic
  search plus graph relationships across tasks, ADRs, files, agents, and
  events.
- The event log remains canonical, preserving Phase 1's audit model.
- Local-first remains possible with a fully local Cognee profile.
- The private/shared namespace split reduces memory poisoning risk.
- The schema gives ADR-0008 and ADR-0009 a concrete substrate without
  pre-deciding their implementation details.

**Negative**

- Cognee is more operationally complex than a vector-only memory library.
- Local graph defaults such as Kuzu are not ideal for concurrent multi-process
  writers; the Phase 2 implementation must serialize writes through the
  Librarian or move to Neo4j for multi-agent concurrency.
- Local LLM/embedding quality and speed will directly affect extraction
  quality. Bad extraction can create plausible but wrong memories.
- Cognee configuration must be guarded carefully to prevent accidental cloud
  fallback.

**Neutral**

- No code is approved by this ADR.
- No new repository directory layout is approved by this ADR beyond the
  existing reserved `memory/` area.
- ADR-0008 still owns write authorization and promotion rules.
- ADR-0009 still owns the MCP tool names, permissions, and response shapes.

## Rejected Alternatives

### Backend: Mem0 as primary memory backend

Mem0 is attractive because it is simple, agent-focused, and has a strong
memory API. It is also Apache-2.0 and self-hostable. However, current Mem0 OSS
v3 removed explicit graph-store support and replaced it with entity linking in
the vector store. That may be a good simplification for conversational memory,
but Agentic OS needs durable graph relationships among tasks, ADRs, handoffs,
files, commits, and agents. Reconstructing those relationships outside Mem0
would push us toward a parallel graph layer, eliminating the simplicity
benefit. Mem0 remains a credible fallback if Phase 2 discovers that graph
queries are unnecessary or too expensive.

### Backend: Letta as primary memory backend

Letta is strong when the goal is a stateful agent runtime: agents, memory
blocks, messages, runs, tools, and archival memory are first-class concepts.
That is not the Phase 2 goal. Agentic OS already has multiple agents with
their own runtimes, and it needs a shared memory substrate those agents can
query through MCP. Letta would either become another agent runtime competing
with Codex/Claude/OpenClaw/Hermes, or we would use only a thin slice of it as a
memory database. Both paths are heavier and less direct than Cognee for this
phase. Letta may become useful later for experiments with stateful resident
agents, but not as the shared Phase 2 memory backend.

### Backend: roll-your-own SQLite + vector + graph

Rolling our own would maximize local-first control and make rebuildability
straightforward. It is rejected because the hidden work is exactly where memory
systems fail: ingestion pipelines, chunking, embeddings, entity extraction,
deduplication, graph updates, ranking, confidence scoring, schema migration,
and MCP exposure. Agentic OS should spend Phase 2 deciding policy and
integration boundaries, not reinventing a memory engine. A rebuildable schema
and canonical event log give us an escape hatch if Cognee proves unsuitable.

### Canonical store: make Cognee memory canonical

Rejected. A memory database is a derived interpretation of project facts, not
the audit trail itself. If memory became canonical, bugs in extraction,
embedding drift, or graph migrations could silently rewrite project history.
The canonical sources stay as files, JSONL logs, and Git history. Memory can be
deleted and rebuilt.

### Canonical store: rewrite `logs/agent-events.jsonl` into memory only

Rejected. Removing or demoting the JSONL log would break ADR-0004's audit
model and make simple file review harder. JSONL is boring, diffable, and
agent-readable. It remains the durable event stream; episodic memory is the
indexed view over it.

### Namespace model: all agents can write shared memory directly

Rejected. Direct shared writes are fast, but they make memory poisoning and
confidence drift likely. An agent that misunderstands a review comment could
promote a false project fact that later agents treat as established. Private
namespaces preserve learning and scratch context without contaminating shared
truth. ADR-0008's Librarian path is the deliberate friction that shared memory
needs.

### Namespace model: all memory is private per agent

Rejected. Purely private memory avoids contamination, but it fails the main
purpose of Agentic OS: agents operating together over shared project state. It
would duplicate indexing work and keep every agent in its own small world.
Shared read access plus controlled shared writes is the better balance.

### Local-first model: allow cloud providers by default

Rejected. Cloud defaults are convenient and may produce better extraction, but
they violate the Phase 1 local-first guarantee and can leak project code,
handoffs, task notes, and decision history. Cloud providers can be optional
behind explicit flags and approval, never the default.

## References

- Cognee local MCP setup: https://docs.cognee.ai/cognee-mcp/mcp-local-setup
- Cognee graph stores: https://docs.cognee.ai/setup-configuration/graph-stores
- Cognee vector stores: https://docs.cognee.ai/setup-configuration/vector-stores
- Cognee local no-API-key setup: https://docs.cognee.ai/guides/local-setup
- Cognee repository/license: https://github.com/topoteretes/cognee
- Mem0 OSS overview: https://docs.mem0.ai/open-source/overview
- Mem0 OSS v3 graph-memory migration note: https://docs.mem0.ai/migration/oss-v2-to-v3
- Mem0 repository/license: https://github.com/mem0ai/mem0
- Letta memory overview: https://docs.letta.com/guides/agents/memory
- Letta self-hosting: https://docs.letta.com/guides/selfhosting
- Letta license: https://github.com/letta-ai/letta/blob/main/LICENSE

## Sign-off

- [ ] human
- [ ] claude (reviewer)
