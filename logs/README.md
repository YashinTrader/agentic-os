# Logs

`agent-events.jsonl` is the append-only event log shared by all agents.
See `docs/AGENT_PROTOCOL.md` §6 for the schema.

Rules:
- Append only. Never edit prior lines.
- One JSON object per line.
- UTC timestamps (ISO-8601, `Z` suffix).
