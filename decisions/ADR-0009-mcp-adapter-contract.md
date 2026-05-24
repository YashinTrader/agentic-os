# ADR-0009: MCP adapter contract for memory access

- Status: **Accepted**
- Date: 2026-05-24
- Deciders: human (final sign-off), claude (reviewer), codex (author)
- Depends on: ADR-0007
- Related: ADR-0007, ADR-0008, AGENT_PROTOCOL.md

## Context

ADR-0007 accepted a local-first memory architecture built around Cognee,
rebuildability from canonical repo files, and three namespaces: `shared`,
`agent/<name>`, and `system/derived`. ADR-0008 proposes the Librarian as the
only writer to shared memory.

Agents need one stable access contract for memory. Direct Cognee imports would
couple every agent to the backend. A plain HTTP API would work for the
dashboard, but it would be less natural for local agent clients that already
know how to discover and call tools. Extending the Phase 1 file-only pattern
would preserve simplicity, but it would force every agent to implement search,
ranking, graph traversal, and authorization behavior itself.

MCP is the right boundary because it gives local agents a standard tool
interface while leaving the backend replaceable.

## Decision

Expose Agentic OS memory through a **versioned MCP server** named
`agentic-os-memory`.

Phase 2.1 implements read-only tools. Phase 2.2 may enable Librarian-only write
tools behind an explicit feature flag after ADR-0008 is signed. No general
agent receives direct write access to shared memory.

### 1. Why MCP

MCP is selected over plain HTTP, direct library imports, and file-only access.

| Option | Decision | Rationale |
|--------|----------|-----------|
| MCP tools | accepted | Standard discovery and invocation model for agent clients; keeps backend hidden; supports stdio for local tools and local HTTP for dashboard use. |
| Plain HTTP/JSON | rejected as primary | Good for dashboards, but agents would need custom client glue and tool descriptions. We will still use MCP Streamable HTTP for dashboard transport. |
| Direct Cognee import | rejected | Couples every agent to Cognee APIs and Python environment; makes future backend changes expensive. |
| File-only access | rejected for memory queries | Canonical files remain source of truth, but search, graph traversal, ranking, and namespace checks need a real service boundary. |

The MCP server exposes memory operations as `tools`, not as prompts. It may
also expose read-only resources later, but tools are the Phase 2 contract
because each operation needs structured inputs, filtering, pagination, and
typed errors.

### 2. Protocol Version

The Agentic OS memory contract version is independent from the MCP protocol
version.

```yaml
contract_name: agentic-os-memory
contract_version: 0.1.0
mcp_protocol_target: 2025-06-18
```

Rules:

- Patch version changes may clarify descriptions or add optional output fields.
- Minor version changes may add new tools or optional input fields.
- Major version changes may remove or rename tools and require a new ADR.
- Every response includes `contract_version`.
- Clients may send `contract_version`; unsupported major versions return
  `UNSUPPORTED_CONTRACT_VERSION`.

### 3. Read API Surface (Phase 2.1)

All read tools are available to normal agents and dashboard users with read
permission. They never mutate memory.

#### `memory.search`

Hybrid semantic, keyword, and graph-aware search over allowed namespaces.

Input:

```json
{
  "query": "string, required",
  "type": "semantic_fact | short_term_summary | persona | episodic_event | entity | repo_chunk | null",
  "namespaces": ["shared", "system/derived"],
  "top_k": 10,
  "include_private": false,
  "refs": {
    "tasks": ["T-0019"],
    "adrs": ["ADR-0007"],
    "files": ["docs/AGENT_PROTOCOL.md"]
  }
}
```

Defaults:

- `namespaces`: `["shared", "system/derived"]`;
- `top_k`: `10`;
- maximum `top_k`: `50`;
- `include_private`: `false`.

Output:

```json
{
  "contract_version": "0.1.0",
  "results": [
    {
      "id": "memory:...",
      "type": "semantic_fact",
      "namespace": "shared",
      "content": "...",
      "score": 0.92,
      "confidence": 0.95,
      "source": {"kind": "adr", "path": "decisions/ADR-0007-memory-architecture.md"},
      "refs": {"tasks": [], "adrs": ["ADR-0007"], "events": [], "files": []}
    }
  ],
  "next_cursor": null
}
```

Errors:

- `INVALID_ARGUMENT` for empty query, invalid type, or `top_k > 50`;
- `FORBIDDEN_NAMESPACE` when the caller requests private memory it cannot read;
- `BACKEND_UNAVAILABLE` when the memory backend cannot answer.

#### `memory.get`

Fetch one memory record by ID.

Input:

```json
{
  "id": "memory:<stable-id>",
  "include_neighbors": false
}
```

Output:

```json
{
  "contract_version": "0.1.0",
  "record": {
    "id": "memory:<stable-id>",
    "type": "entity",
    "namespace": "shared",
    "content": "...",
    "source": {},
    "created_at": "2026-05-24T00:00:00Z",
    "created_by": "librarian",
    "confidence": 1.0,
    "refs": {},
    "visibility": "shared",
    "status": "active",
    "ttl": null,
    "metadata": {}
  },
  "neighbors": [
    {
      "nodes": [
        {"id": "memory:entity:task:T-0019", "type": "entity", "label": "T-0019"}
      ],
      "edges": [
        {"from": "memory:<stable-id>", "to": "memory:entity:task:T-0019", "type": "references"}
      ]
    }
  ]
}
```

`neighbors` is an empty list when `include_neighbors` is false. When
`include_neighbors` is true, it contains graph objects with the same `nodes`
and `edges` shape used by `memory.graph_neighbors`.

Errors:

- `NOT_FOUND` when the ID is unknown;
- `FORBIDDEN_NAMESPACE` when the caller cannot read the namespace.

#### `memory.list_entities`

Browse canonical entity records.

Input:

```json
{
  "entity_type": "task | adr | agent | person | file | branch | pr | commit | null",
  "query": "string | null",
  "limit": 50,
  "cursor": null
}
```

Output:

```json
{
  "contract_version": "0.1.0",
  "entities": [
    {
      "id": "memory:entity:adr:ADR-0007",
      "entity_type": "adr",
      "canonical_id": "ADR-0007",
      "name": "Memory architecture for Agentic OS",
      "aliases": [],
      "relations": []
    }
  ],
  "next_cursor": null
}
```

Errors:

- `INVALID_ARGUMENT` for invalid entity type or limit;
- `BACKEND_UNAVAILABLE`.

#### `memory.timeline`

Return episodic records for an entity.

Input:

```json
{
  "entity_id": "T-0019 | ADR-0007 | memory:<id>",
  "since": "2026-05-24T00:00:00Z",
  "until": null,
  "event_types": ["task_created", "status_changed"],
  "limit": 100,
  "cursor": null
}
```

Output:

```json
{
  "contract_version": "0.1.0",
  "events": [
    {
      "id": "memory:episodic:...",
      "event_type": "status_changed",
      "actor": "codex",
      "occurred_at": "2026-05-24T00:00:00Z",
      "event_ref": "logs/agent-events.jsonl:42",
      "task_id": "T-0019",
      "content": "T-0019 moved to review."
    }
  ],
  "next_cursor": null
}
```

Errors:

- `NOT_FOUND` when the entity is unknown;
- `INVALID_ARGUMENT` for bad timestamps or limit.

#### `memory.graph_neighbors`

Traverse graph relationships from a memory record or entity.

Input:

```json
{
  "id": "memory:<id> | T-0019 | ADR-0007",
  "depth": 1,
  "relation_types": ["depends_on", "references", "supersedes"],
  "limit": 100
}
```

Output:

```json
{
  "contract_version": "0.1.0",
  "start": "memory:<id>",
  "nodes": [
    {"id": "memory:entity:adr:ADR-0007", "type": "entity", "label": "ADR-0007"}
  ],
  "edges": [
    {"from": "memory:entity:task:T-0020", "to": "memory:entity:adr:ADR-0007", "type": "depends_on"}
  ]
}
```

Defaults and limits:

- default `depth`: `1`;
- maximum `depth`: `2` in Phase 2.1;
- maximum `limit`: `250`.

Errors:

- `NOT_FOUND`;
- `INVALID_ARGUMENT` for depth greater than the maximum;
- `BACKEND_UNAVAILABLE`.

### 4. Write API Surface (Phase 2.2, Feature-Flagged)

Write tools are not available in Phase 2.1. They appear in `tools/list` only
when all of the following are true:

- ADR-0008 is signed;
- `AGENTIC_OS_MEMORY_WRITES=true`;
- caller identity is `librarian`;
- the local server config allows write tools.

#### `memory.write`

Create or update a shared memory record. Librarian only.

Input:

```json
{
  "idempotency_key": "memory-write:<stable-id>",
  "record": {
    "id": "memory:<stable-id>",
    "type": "semantic_fact",
    "namespace": "shared",
    "content": "...",
    "source": {},
    "created_at": "2026-05-24T00:00:00Z",
    "created_by": "librarian",
    "confidence": 0.9,
    "refs": {},
    "visibility": "shared",
    "status": "active",
    "ttl": null,
    "metadata": {}
  },
  "undo_record": {
    "write_id": "memory-write:<stable-id>",
    "operation": "create",
    "previous_record": null,
    "new_record": {}
  }
}
```

Output:

```json
{
  "contract_version": "0.1.0",
  "write_id": "memory-write:<stable-id>",
  "record_id": "memory:<stable-id>",
  "status": "created | updated | duplicate_ignored"
}
```

Errors:

- `WRITES_DISABLED`;
- `FORBIDDEN_CALLER`;
- `INVALID_RECORD`;
- `MISSING_UNDO_RECORD`;
- `LOW_CONFIDENCE`;
- `UNCITED_CLAIM`;
- `CONFLICT_DETECTED`.

#### `memory.retract`

Mark a shared memory record as retracted. Librarian only.

Input:

```json
{
  "idempotency_key": "memory-retract:<stable-id>",
  "record_id": "memory:<stable-id>",
  "reason": "superseded by ADR-0010",
  "source_refs": [{"kind": "adr", "id": "ADR-0010"}]
}
```

Output:

```json
{
  "contract_version": "0.1.0",
  "record_id": "memory:<stable-id>",
  "status": "retracted"
}
```

Errors:

- `WRITES_DISABLED`;
- `FORBIDDEN_CALLER`;
- `NOT_FOUND`;
- `MISSING_SOURCE_REFS`.

#### `memory.mark_disputed`

Attach a dispute annotation without overwriting the active record.

Input:

```json
{
  "idempotency_key": "memory-dispute:<stable-id>",
  "record_id": "memory:<stable-id>",
  "conflicting_source_refs": [{"kind": "task", "id": "T-0020"}],
  "reason": "candidate contradicts accepted ADR"
}
```

Output:

```json
{
  "contract_version": "0.1.0",
  "record_id": "memory:<stable-id>",
  "status": "disputed"
}
```

Errors:

- `WRITES_DISABLED`;
- `FORBIDDEN_CALLER`;
- `NOT_FOUND`;
- `MISSING_SOURCE_REFS`.

### 5. Auth and Identity

For stdio transport, the server reads caller identity and capabilities from the
local launch environment or config file:

```text
AGENTIC_OS_AGENT_ID=codex
AGENTIC_OS_MEMORY_ROLE=reader | librarian
```

For local HTTP transport, the server requires bearer-token authentication and
binds only to `127.0.0.1`. The token maps to the same identity fields:

```json
{
  "agent_id": "dashboard",
  "role": "reader",
  "scopes": ["memory:read"]
}
```

Write scopes are never granted to dashboard or general agent tokens in Phase 2.
The only write-capable identity is `librarian`, and write tools must also be
feature-flagged on. Token passthrough is forbidden; the memory MCP server must
accept only tokens minted for itself.

### 6. Local-First Transport

Phase 2 supports two local transports:

| Transport | Use | Binding |
|-----------|-----|---------|
| stdio | local agent clients such as Codex CLI, Claude desktop, Cursor, and compatible tools | client launches server as subprocess |
| Streamable HTTP | local dashboard or browser-adjacent tools | `127.0.0.1` only |

No remote MCP servers are allowed in Phase 2. Streamable HTTP servers must
validate `Origin`, require auth, and bind to localhost. If older clients need
HTTP+SSE compatibility, that is a future compatibility task, not a Phase 2.1
requirement.

### 7. Error Model

All tools return MCP tool results. Successful results include structured JSON.
Recoverable domain errors return `isError: true` with this shape:

```json
{
  "code": "INVALID_ARGUMENT",
  "message": "top_k must be between 1 and 50",
  "details": {"field": "top_k"},
  "retryable": false
}
```

Canonical error codes:

| Code | Retryable | Meaning |
|------|-----------|---------|
| `INVALID_ARGUMENT` | false | Input schema or value is invalid. |
| `NOT_FOUND` | false | Requested record/entity does not exist. |
| `FORBIDDEN_NAMESPACE` | false | Caller lacks access to namespace. |
| `FORBIDDEN_CALLER` | false | Caller identity cannot invoke the tool. |
| `WRITES_DISABLED` | false | Write tools are disabled by feature flag. |
| `UNSUPPORTED_CONTRACT_VERSION` | false | Client requested an incompatible major version. |
| `BACKEND_UNAVAILABLE` | true | Cognee or local storage cannot answer. |
| `CONFLICT_DETECTED` | false | Write contradicts active memory and must be disputed. |
| `LOW_CONFIDENCE` | false | Write violates ADR-0008 threshold. |
| `UNCITED_CLAIM` | false | Write lacks canonical source refs. |
| `MISSING_UNDO_RECORD` | false | Write lacks required undo payload. |
| `MISSING_SOURCE_REFS` | false | Retraction/dispute lacks source refs. |

Unexpected server failures should use MCP/JSON-RPC server errors, but domain
failures should use the structured tool error above so agents can recover.

### 8. Test Contract

Every tool must have fixture-based tests that run without Cognee or any real
backend. The fake backend must cover:

- empty store;
- namespace denial;
- duplicate records;
- search with deterministic ranking;
- graph traversal depth limit;
- timeline filtering;
- write tools hidden when writes are disabled;
- write tools rejecting non-Librarian callers;
- idempotent write replay;
- backend unavailable errors.

Gating tests for PR merge use the fixture backend only. Real Cognee tests run
behind an explicit slow/integration flag because they require local services,
model configuration, and larger dependencies.

### 9. Resources and Prompts

Phase 2.1 does not expose memory as MCP prompts. Prompts shape model behavior,
which is too close to persona injection and should not be mixed with read
retrieval.

The server may expose records as read-only MCP resources in a later task, for
example `memory://record/<id>`. That is optional. The required Phase 2.1
contract is the tool surface above.

## Consequences

**Positive**

- Agents get one stable tool contract independent of Cognee internals.
- Local agent clients can use stdio without running a network service.
- The dashboard can use local HTTP without forcing CLI agents onto HTTP.
- Write access is mechanically absent in Phase 2.1 and double-gated in Phase
  2.2 by identity and feature flag.
- Fixture tests make the contract reviewable before real memory dependencies
  are installed.

**Negative**

- MCP adds an adapter layer instead of letting Python callers import Cognee
  directly.
- Dashboard integration must speak MCP over local HTTP or use a small client
  wrapper.
- Contract versioning creates maintenance overhead even before implementation.

**Neutral**

- This ADR does not implement the adapter.
- This ADR does not choose a Python/TypeScript MCP SDK.
- This ADR does not approve remote MCP, cloud auth, or public network binding.
- This ADR does not relax ADR-0008's single-writer rule.

## Rejected Alternatives

### Plain HTTP/JSON as the primary API

Rejected as the primary contract because Agentic OS is agent-first. MCP gives
agents tool discovery, schemas, and a standard invocation shape. HTTP remains
useful as MCP's local Streamable HTTP transport for dashboard access.

### Direct library imports

Rejected because they couple every agent to Cognee, Python packaging, and the
memory backend's internal API. A future backend replacement should change the
adapter, not every agent.

### File-only memory access

Rejected because files are canonical but not sufficient for query-time memory.
Graph traversal, ranking, namespace filtering, and conflict-aware retrieval
need a service boundary. The file system remains the rebuild source, not the
query API.

### Expose write tools immediately

Rejected. Phase 2.1 proves read-only memory first. Shared writes wait for
ADR-0008 sign-off, a feature flag, and a Librarian identity. This keeps memory
pollution risk contained while retrieval matures.

### Remote MCP server

Rejected for Phase 2. Remote transport changes the trust boundary and would
require a fuller OAuth/security design. Local stdio and localhost HTTP satisfy
the current multi-agent workstation use case.

## References

- MCP base protocol overview: https://modelcontextprotocol.io/specification/2025-06-18/basic
- MCP lifecycle: https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- MCP transports: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- MCP tools: https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- MCP authorization: https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization

## Sign-off

- [x] human - Gabriel Achim approved on 2026-05-24
- [x] claude (reviewer) - Claude Opus 4.7 approved PR #10 on 2026-05-24
