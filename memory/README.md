# Memory (Phase 2 - Local Profile)

This directory contains the Phase 2.1 local-first Cognee bootstrap profile.
The profile is configuration only: it does not ingest repository data, create a
memory database, start a server, or call external APIs.

## Files

- `cognee-local.env.example`: local Cognee profile for Ollama, Fastembed,
  Kuzu, LanceDB, and SQLite.
- `cognee/`: ignored local runtime directory for generated Cognee system and
  data files.
- `candidates/`: ignored local output directory for Librarian dry-run
  candidate streams.

## Dry-Run Check

Run this from the repository root:

```bash
python3 scripts/check_cognee_profile.py
```

For machine-readable output:

```bash
python3 scripts/check_cognee_profile.py --json
```

The checker validates shape and local-first guardrails only. It intentionally
does not import Cognee, contact Ollama, create databases, or run ingestion.

## Librarian Dry Runs

T-0025 adds a batchable Librarian policy skeleton:

```bash
python3 scripts/memory_librarian.py --jsonl
```

The command reads deterministic extractor output, validates citation and
confidence policy, emits candidate decisions plus undo records, and can append
a run-summary audit event. It does not write to Cognee or any shared memory
backend in Phase 2.1.

Audit events use ADR-0004's allowed `note` event type and include structured
`counts` for candidates, writes, skips, and conflicts.

To store a local candidate stream:

```bash
python3 scripts/memory_librarian.py --jsonl --output memory/candidates/latest.jsonl
```

Manual CLI runs timestamp generated undo records with current UTC by default.
Tests and repeatable fixtures can still pass `--run-ts` or call
`run_librarian(..., run_ts=...)` for deterministic output.

### Dry-Run Limitations

- The default circuit breaker threshold is 10 bad candidates in one run. Tests
  may lower it to exercise the breaker. This is a Phase 2.1 heuristic, not a
  final operational limit.
- Record signatures currently cover `id`, `type`, `content`, and source refs.
  Metadata-only changes, such as an ADR status moving from proposed to
  accepted, may be treated as duplicates until update semantics land.
- Conflict decisions include both the current record and `existing_record`, but
  the first record seen in a run is treated as the existing record. Later backend
  work should prefer canonical task state when multiple directories contain the
  same task ID.
- Dry runs deduplicate only within one run. Cross-run idempotency requires a
  backend existence check or persisted candidate ledger in a future task.

## Local Defaults

The checked-in profile uses:

| Layer | Default |
|-------|---------|
| LLM | Ollama with `llama3.1:8b` |
| Embeddings | Fastembed with `sentence-transformers/all-MiniLM-L6-v2` |
| Graph store | Kuzu |
| Vector store | LanceDB |
| Relational store | SQLite |

Cloud providers are disabled by default with
`AGENTIC_OS_ENABLE_CLOUD_PROVIDERS="false"`. Repository ingestion is disabled
with `AGENTIC_OS_INGESTION_ENABLED="false"`.

Important: Cognee can fall back to OpenAI if only the LLM or only the
embedding provider is configured locally. Agentic OS therefore requires both
`LLM_PROVIDER` and `EMBEDDING_PROVIDER` to be local in the same profile.
OpenAI-compatible local LLM servers are acceptable only when `LLM_ENDPOINT`
points at `localhost` or `127.0.0.1`.

## Before Real Ingestion

Phase 2.1 stops at configuration bootstrap. A future ingestion task must:

- copy the example profile into a local `.env` or shell environment;
- install and run Ollama locally;
- pull the default model with `ollama pull llama3.1:8b`;
- keep both LLM and embedding providers local;
- explicitly flip ingestion on in a reviewed task.

## Sources

- Cognee local no-API-key setup:
  https://docs.cognee.ai/guides/local-setup
- Cognee graph stores:
  https://docs.cognee.ai/setup-configuration/graph-stores
- Cognee vector stores:
  https://docs.cognee.ai/setup-configuration/vector-stores
- Cognee relational databases:
  https://docs.cognee.ai/setup-configuration/relational-databases
