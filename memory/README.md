# Memory (Phase 2 - Local Profile)

This directory contains the Phase 2.1 local-first Cognee bootstrap profile.
The profile is configuration only: it does not ingest repository data, create a
memory database, start a server, or call external APIs.

## Files

- `cognee-local.env.example`: local Cognee profile for Ollama, Fastembed,
  Kuzu, LanceDB, and SQLite.
- `cognee/`: ignored local runtime directory for generated Cognee system and
  data files.

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
