# Roles Registry (Phase 2.2)

The roles registry defines **agent responsibilities** — including skill/MCP access,
governance flags, approval requirements, and eligibility constraints.

## Canonical File

- `roles/registry.yaml` — source of truth for all registered roles

## Example Entries

`roles/examples/` contains standalone YAML examples mirroring registry entries.
Use them as templates when adding new roles.

## CLI

```bash
python scripts/list_roles.py
python scripts/list_roles.py --agent codex
python scripts/list_roles.py --risk medium
python scripts/list_roles.py --can-execute true
python scripts/list_roles.py --json
```

## Phase 2.2 Scope

- Registry + validation + dashboard read views only
- No role execution, no agent launching, no MCP calls

See `docs/SKILLS_AND_MCPS.md` for the full protocol.