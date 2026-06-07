# Memory

Phase 2.3 adds **Obsidian vault sync configuration** in `obsidian_mapping.yaml`.

The repository remains the operational source of truth. Obsidian receives a
read-only human-readable mirror via `scripts/sync_obsidian.py`.

## Configuration

Edit `memory/obsidian_mapping.yaml` locally:

- Set `vault_path` to your Obsidian vault directory (do not commit personal paths).
- Set `sync_enabled: true` only when you intend to run real syncs.
- Keep `dry_run_default: true` until you verify output.

## Usage

```bash
python scripts/sync_obsidian.py --dry-run
python scripts/sync_obsidian.py --vault "C:\path\to\vault"
```

See `docs/OBSIDIAN_SYNC.md` for full documentation.