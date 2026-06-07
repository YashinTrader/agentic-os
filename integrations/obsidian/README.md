# Obsidian Integration

One-way filesystem sync from the Agentic OS repository into a local Obsidian vault.

## Modules

| Module | Purpose |
|--------|---------|
| `mapping.py` | Load `memory/obsidian_mapping.yaml`, resolve vault paths |
| `vault_writer.py` | Safe path joins, filename sanitization, no deletes |
| `sync_to_vault.py` | Collect repo sources and write Markdown notes |

## Entry Point

Use `scripts/sync_obsidian.py` — not the modules directly — unless extending tests.

## Safety

- Writes only under `{vault_path}/{vault_root_folder}/` (default `AgenticOS/`)
- Never deletes vault files
- Blocks path traversal
- Default dry-run when `vault_path` is unset

See `docs/OBSIDIAN_SYNC.md`.