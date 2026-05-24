# Cognee Local Profile

T-0023 adds the Phase 2.1 local-first Cognee bootstrap profile. This is a
configuration and validation slice only. It does not run ingestion and does
not start Cognee.

## Decision Mapping

ADR-0007 requires a local-first default memory profile:

| ADR-0007 requirement | T-0023 profile value |
|----------------------|----------------------|
| Local LLM | `LLM_PROVIDER="ollama"` |
| 7B-14B class default model | `LLM_MODEL="llama3.1:8b"` |
| Local embeddings | `EMBEDDING_PROVIDER="fastembed"` |
| Local graph store | `GRAPH_DATABASE_PROVIDER="kuzu"` |
| Local vector store | `VECTOR_DB_PROVIDER="lancedb"` |
| Local relational metadata | `DB_PROVIDER="sqlite"` |
| Cloud off by default | `AGENTIC_OS_ENABLE_CLOUD_PROVIDERS="false"` |
| No ingestion in bootstrap | `AGENTIC_OS_INGESTION_ENABLED="false"` |

## Validation

Run:

```bash
python3 scripts/check_cognee_profile.py --json
```

The checker fails if:

- required keys are missing;
- cloud providers are enabled;
- LLM or embedding provider is non-local;
- only one of the model providers is local;
- ingestion is enabled;
- graph/vector/relational providers drift from Kuzu, LanceDB, and SQLite.

The checker uses only the Python standard library. It does not import Cognee,
connect to Ollama, create files under `memory/cognee/`, or ingest repository
content.

## Dependency

`requirements.txt` now includes `cognee==1.1.0`, the current PyPI release at
implementation time. The dependency is declared for bootstrap completeness,
but the dry-run tests do not import it and do not require optional services.

## Source Notes

Cognee's local setup documentation says both the LLM provider and embedding
provider must be configured together for a local setup; otherwise the
unconfigured side can fall back to OpenAI. The same docs show Ollama plus
Fastembed with `llama3.1:8b` and
`sentence-transformers/all-MiniLM-L6-v2`. Cognee's storage docs identify Kuzu,
LanceDB, and SQLite as local/default development stores.

Official references:

- https://docs.cognee.ai/guides/local-setup
- https://docs.cognee.ai/setup-configuration/llm-providers
- https://docs.cognee.ai/setup-configuration/embedding-providers
- https://docs.cognee.ai/setup-configuration/graph-stores
- https://docs.cognee.ai/setup-configuration/vector-stores
- https://docs.cognee.ai/setup-configuration/relational-databases
