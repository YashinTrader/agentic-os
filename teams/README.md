# Teams Registry (Phase 2.2)

The teams registry maps **agents to roles** — including skills, MCP access,
approval policies, and task suitability metadata.

## Canonical File

- `teams/registry.yaml` — source of truth for all registered teams

## Example Entries

`teams/examples/` contains standalone YAML examples mirroring registry entries.
Use them as templates when adding new teams.

## CLI

```bash
python scripts/list_teams.py
python scripts/list_teams.py --status active
python scripts/list_teams.py --agent codex
python scripts/list_teams.py --skill implement-python-cli
python scripts/list_teams.py --json
python scripts/suggest_team.py --label dashboard
```

## Phase 2.2 Scope

- Registry + validation + dashboard read views only
- `planned` teams are valid and do not fail validation
- No team orchestration, agent launching, or MCP calls

See `docs/SKILLS_AND_MCPS.md` for the full protocol.