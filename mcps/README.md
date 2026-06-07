# MCP Registry (Phase 2.1)

The MCP registry catalogs **configured or planned MCP servers** — transport,
capabilities, agent eligibility, secrets requirements, and governance.

## Canonical File

- `mcps/registry.yaml` — source of truth for all registered MCPs

## Example Entries

`mcps/examples/` contains standalone YAML examples. **Never store secrets** in
registry files; use `env_vars_required` to name expected variables only.

## CLI

```bash
python scripts/list_mcps.py
python scripts/list_mcps.py --status planned
python scripts/list_mcps.py --agent codex
python scripts/list_mcps.py --json
```

## Phase 2.1 Scope

- Configuration metadata only
- `planned` MCPs are valid and do not fail validation
- No MCP execution, installation, or API calls

See `docs/SKILLS_AND_MCPS.md` for the full protocol.