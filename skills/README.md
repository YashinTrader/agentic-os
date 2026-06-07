# Skills Registry (Phase 2.1)

The skills registry describes **reusable capabilities** the Agentic OS can assign
to agents — including eligibility, dependencies, risk, and approval requirements.

## Canonical File

- `skills/registry.yaml` — source of truth for all registered skills

## Example Entries

`skills/examples/` contains standalone YAML examples mirroring registry entries.
Use them as templates when adding new skills.

## CLI

```bash
python scripts/list_skills.py
python scripts/list_skills.py --agent codex
python scripts/list_skills.py --risk medium
python scripts/list_skills.py --json
```

## Phase 2.1 Scope

- Registry + validation + dashboard read views only
- No skill execution, no agent launching, no MCP calls

See `docs/SKILLS_AND_MCPS.md` for the full protocol.