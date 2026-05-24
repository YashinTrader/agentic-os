# ADR-0009: MCP adapter contract for memory access (PROPOSAL STUB)

- Status: **Draft - Codex to author after ADR-0007 signed**
- Date: 2026-05-24
- Deciders: human (final sign-off), claude (reviewer), codex (author)
- Depends on: ADR-0007
- Related: ADR-0007, ADR-0008, AGENT_PROTOCOL.md

## Context

ADR-0007 accepted a local-first memory architecture for Agentic OS. Agents
must access that memory through a stable adapter contract rather than direct
backend calls. ADR-0009 decides whether MCP is that contract and specifies the
minimum read and write surfaces before implementation begins.

## Decision

Codex must author this section in T-0021. The final ADR must answer:

### 1. Why MCP

Justify Model Context Protocol as the access layer for memory. Alternatives to
evaluate:

- plain HTTP/JSON API;
- direct library import per agent;
- file-based access extending Phase 1's pattern.

If MCP does not win, propose the alternative and explain the tradeoff.

### 2. Read API surface (Phase 2.1, first to ship)

Define the minimum read endpoints:

- `memory.search(query, type?, top_k)` - vector plus keyword hybrid;
- `memory.get(id)` - fetch a record by ID;
- `memory.list_entities(filter)` - entity browse;
- `memory.timeline(entity_id, since?, until?)` - episodic records for an
  entity;
- `memory.graph_neighbors(id, depth=1)` - graph traversal.

For each endpoint, specify input schema, output schema, and error modes.

### 3. Write API surface (Phase 2.2, behind a flag)

Write endpoints are Librarian-only per ADR-0008. Document:

- auth and identity: how the adapter knows it is talking to the Librarian;
- idempotency: every write carries a client-side ID and replays are no-ops;
- feature flag: writes are disabled by default in Phase 2.1.

### 4. Local-first transport

MCP over stdio for local agents such as Codex CLI, Claude desktop, and Cursor;
MCP over local HTTP for the dashboard. No remote MCP servers in Phase 2 unless
a later ADR explicitly approves them.

### 5. Versioning

The adapter contract is versioned. Breaking changes require a new ADR and a
deprecation window. Codex must define the versioning scheme.

### 6. Test contract

Every endpoint must have a fixture-based test that runs without the real
backend. Real-backend tests run separately and are not gating for PR merge.

## Consequences

To be authored in T-0021. The final ADR must define the integration boundary
clearly enough for Phase 2.1 implementation tasks to build against it without
guessing.

## Sign-off

- [ ] human
- [ ] claude (reviewer)
